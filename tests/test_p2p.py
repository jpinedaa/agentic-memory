"""Tests for the P2P protocol layer.

These tests verify types, serialization, routing, gossip, node lifecycle,
P2PMemoryClient, and LocalAgentState — all without external dependencies
(no Neo4j, no API key, no network).
"""
# pylint: disable=missing-function-docstring  # test names are self-documenting
# pylint: disable=missing-class-docstring  # test class names are self-documenting
# pylint: disable=import-outside-toplevel  # tests import inside methods to scope construction
# pylint: disable=protected-access  # tests verify internal state
# pylint: disable=unused-argument  # pytest fixtures injected by name

import asyncio
import time

import pytest

from src.p2p.types import Capability, PeerInfo, PeerState, generate_node_id
from src.p2p.messages import Envelope
from src.p2p.routing import RoutingTable, METHOD_CAPABILITIES
from src.p2p.local_state import LocalAgentState


# ── Types ───────────────────────────────────────────────────────────


class TestCapability:
    def test_capability_values(self):
        assert Capability.STORE == "store"
        assert Capability.LLM == "llm"
        assert Capability.INFERENCE == "inference"
        assert Capability.VALIDATION == "validation"
        assert Capability.CLI == "cli"

    def test_capability_from_string(self):
        assert Capability("store") == Capability.STORE
        assert Capability("llm") == Capability.LLM


class TestPeerInfo:
    def _make_info(self, **kwargs):
        defaults = {
            "node_id": "node-abc123",
            "capabilities": frozenset({Capability.STORE, Capability.LLM}),
            "http_url": "http://localhost:9000",
            "ws_url": "ws://localhost:9000/p2p/ws",
            "started_at": 1000.0,
        }
        defaults.update(kwargs)
        return PeerInfo(**defaults)

    def test_frozen(self):
        info = self._make_info()
        with pytest.raises(AttributeError):
            info.node_id = "changed"

    def test_serialization_roundtrip(self):
        info = self._make_info()
        d = info.to_dict()
        info2 = PeerInfo.from_dict(d)
        assert info2.node_id == info.node_id
        assert info2.capabilities == info.capabilities
        assert info2.http_url == info.http_url
        assert info2.ws_url == info.ws_url
        assert info2.started_at == info.started_at
        assert info2.version == info.version

    def test_capabilities_serialized_as_sorted_strings(self):
        info = self._make_info()
        d = info.to_dict()
        assert d["capabilities"] == ["llm", "store"]


class TestPeerState:
    def _make_state(self, **kwargs):
        info = PeerInfo(
            node_id=kwargs.pop("node_id", "node-abc123"),
            capabilities=kwargs.pop("capabilities", frozenset({Capability.STORE})),
            http_url="http://localhost:9000",
            ws_url="ws://localhost:9000/p2p/ws",
        )
        defaults = {"info": info, "status": "alive", "last_seen": time.time(), "heartbeat_seq": 1}
        defaults.update(kwargs)
        return PeerState(**defaults)

    def test_serialization_roundtrip(self):
        state = self._make_state(metadata={"items_processed": 42})
        d = state.to_dict()
        state2 = PeerState.from_dict(d)
        assert state2.info.node_id == state.info.node_id
        assert state2.status == "alive"
        assert state2.heartbeat_seq == 1
        assert state2.metadata["items_processed"] == 42

    def test_mutable(self):
        state = self._make_state()
        state.status = "dead"
        assert state.status == "dead"


class TestGenerateNodeId:
    def test_format(self):
        nid = generate_node_id()
        assert nid.startswith("node-")
        assert len(nid) == 13  # "node-" + 8 hex chars

    def test_unique(self):
        ids = {generate_node_id() for _ in range(100)}
        assert len(ids) == 100


# ── Messages ────────────────────────────────────────────────────────


class TestEnvelope:
    def test_defaults(self):
        e = Envelope(msg_type="ping")
        assert e.msg_type == "ping"
        assert e.sender_id == ""
        assert e.recipient_id == ""
        assert e.ttl == 3
        assert e.reply_to == ""
        assert not e.payload
        assert len(e.msg_id) == 16

    def test_serialization_roundtrip(self):
        e = Envelope(
            msg_type="request",
            sender_id="node-a",
            recipient_id="node-b",
            ttl=2,
            payload={"method": "observe", "args": {"text": "hello"}},
        )
        d = e.to_dict()
        e2 = Envelope.from_dict(d)
        assert e2.msg_type == "request"
        assert e2.sender_id == "node-a"
        assert e2.recipient_id == "node-b"
        assert e2.ttl == 2
        assert e2.payload["method"] == "observe"

    def test_unique_msg_ids(self):
        ids = {Envelope(msg_type="ping").msg_id for _ in range(100)}
        assert len(ids) == 100


# ── Routing ─────────────────────────────────────────────────────────


class TestRoutingTable:
    def _make_peer(self, node_id, capabilities, seq=1):
        info = PeerInfo(
            node_id=node_id,
            capabilities=frozenset(capabilities),
            http_url=f"http://localhost:{9000 + hash(node_id) % 100}",
            ws_url=f"ws://localhost:{9000 + hash(node_id) % 100}/p2p/ws",
        )
        return PeerState(info=info, status="alive", last_seen=time.time(), heartbeat_seq=seq)

    def test_add_and_count(self):
        rt = RoutingTable()
        assert rt.peer_count == 0
        rt.update_peer(self._make_peer("a", {Capability.STORE}))
        assert rt.peer_count == 1

    def test_update_returns_true_for_new(self):
        rt = RoutingTable()
        assert rt.update_peer(self._make_peer("a", {Capability.STORE})) is True

    def test_update_returns_false_for_stale(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("a", {Capability.STORE}, seq=5))
        assert rt.update_peer(self._make_peer("a", {Capability.STORE}, seq=3)) is False

    def test_update_returns_true_for_newer_seq(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("a", {Capability.STORE}, seq=1))
        assert rt.update_peer(self._make_peer("a", {Capability.STORE}, seq=2)) is True

    def test_remove_peer(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("a", {Capability.STORE}))
        rt.remove_peer("a")
        assert rt.peer_count == 0

    def test_remove_nonexistent(self):
        rt = RoutingTable()
        rt.remove_peer("nonexistent")  # should not raise

    def test_find_peers_with_capability(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("a", {Capability.STORE, Capability.LLM}))
        rt.update_peer(self._make_peer("b", {Capability.INFERENCE}))

        store_peers = rt.find_peers_with_capability(Capability.STORE)
        assert len(store_peers) == 1
        assert store_peers[0].info.node_id == "a"

        inference_peers = rt.find_peers_with_capability(Capability.INFERENCE)
        assert len(inference_peers) == 1
        assert inference_peers[0].info.node_id == "b"

    def test_find_peers_excludes_self(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("self", {Capability.STORE}))
        assert rt.find_peers_with_capability(Capability.STORE, exclude="self") == []

    def test_find_peers_excludes_dead(self):
        rt = RoutingTable()
        peer = self._make_peer("a", {Capability.STORE})
        peer.status = "dead"
        rt.update_peer(peer)
        assert rt.find_peers_with_capability(Capability.STORE) == []

    def test_route_method_observe(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("store-llm", {Capability.STORE, Capability.LLM}))
        rt.update_peer(self._make_peer("inference", {Capability.INFERENCE}))

        peer = rt.route_method("observe")
        assert peer is not None
        assert peer.info.node_id == "store-llm"

    def test_route_method_returns_none_when_no_match(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("inference", {Capability.INFERENCE}))
        assert rt.route_method("observe") is None

    def test_route_method_infer_needs_only_llm(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("llm-only", {Capability.LLM}))
        peer = rt.route_method("infer")
        assert peer is not None
        assert peer.info.node_id == "llm-only"

    def test_get_alive_peers(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("alive", {Capability.STORE}))
        dead = self._make_peer("dead", {Capability.STORE})
        dead.status = "dead"
        rt.update_peer(dead)
        assert len(rt.get_alive_peers()) == 1

    def test_get_all_peers(self):
        rt = RoutingTable()
        rt.update_peer(self._make_peer("a", {Capability.STORE}))
        dead = self._make_peer("b", {Capability.STORE})
        dead.status = "dead"
        rt.update_peer(dead)
        assert len(rt.get_all_peers()) == 2

    def test_last_seen_refreshed_on_same_seq(self):
        """Even if heartbeat_seq hasn't changed, last_seen should refresh."""
        rt = RoutingTable()
        old_time = time.time() - 100
        info = PeerInfo(
            node_id="a",
            capabilities=frozenset({Capability.STORE}),
            http_url="http://localhost:9000",
            ws_url="ws://localhost:9000/p2p/ws",
        )
        rt.update_peer(PeerState(info=info, status="alive", last_seen=old_time, heartbeat_seq=5))
        # Same seq, newer last_seen
        new_time = time.time()
        rt.update_peer(PeerState(info=info, status="alive", last_seen=new_time, heartbeat_seq=5))
        peer = rt.get_all_peers()[0]
        assert peer.last_seen == new_time
        assert peer.status == "alive"

    def test_last_seen_not_downgraded(self):
        """Older last_seen with same seq should not overwrite newer."""
        rt = RoutingTable()
        new_time = time.time()
        old_time = new_time - 100
        info = PeerInfo(
            node_id="a",
            capabilities=frozenset({Capability.STORE}),
            http_url="http://localhost:9000",
            ws_url="ws://localhost:9000/p2p/ws",
        )
        rt.update_peer(PeerState(info=info, status="alive", last_seen=new_time, heartbeat_seq=5))
        rt.update_peer(PeerState(info=info, status="alive", last_seen=old_time, heartbeat_seq=5))
        peer = rt.get_all_peers()[0]
        assert peer.last_seen == new_time


class TestMethodCapabilities:
    def test_observe_needs_store_and_llm(self):
        assert METHOD_CAPABILITIES["observe"] == {Capability.STORE, Capability.LLM}

    def test_infer_needs_only_llm(self):
        assert METHOD_CAPABILITIES["infer"] == {Capability.LLM}

    def test_get_recent_observations_needs_only_store(self):
        assert METHOD_CAPABILITIES["get_recent_observations"] == {Capability.STORE}

    def test_all_memory_api_methods_covered(self):
        expected = {
            "observe", "claim", "remember", "infer",
            "get_recent_observations", "get_recent_claims",
            "get_unresolved_contradictions", "get_entities", "clear",
        }
        assert set(METHOD_CAPABILITIES.keys()) == expected


# ── LocalAgentState ─────────────────────────────────────────────────


class TestLocalAgentState:
    async def test_is_processed_initially_false(self):
        state = LocalAgentState()
        assert await state.is_processed("key", "member") is False

    async def test_mark_and_check_processed(self):
        state = LocalAgentState()
        await state.mark_processed("key", "member")
        assert await state.is_processed("key", "member") is True

    async def test_different_keys_independent(self):
        state = LocalAgentState()
        await state.mark_processed("key1", "member")
        assert await state.is_processed("key2", "member") is False

    async def test_try_acquire_first_time(self):
        state = LocalAgentState()
        assert await state.try_acquire("resource", "instance-1") is True

    async def test_try_acquire_same_instance(self):
        state = LocalAgentState()
        await state.try_acquire("resource", "instance-1")
        assert await state.try_acquire("resource", "instance-1") is True

    async def test_try_acquire_different_instance_fails(self):
        state = LocalAgentState()
        await state.try_acquire("resource", "instance-1")
        assert await state.try_acquire("resource", "instance-2") is False

    async def test_close(self):
        state = LocalAgentState()
        await state.close()  # should not raise


# ── Node Message Dispatch ───────────────────────────────────────────


class TestAdvertiseHost:
    """Test that advertise_host controls URLs in PeerInfo."""

    def test_default_uses_listen_host(self):
        from src.p2p.node import PeerNode
        node = PeerNode(
            capabilities={Capability.STORE},
            listen_host="127.0.0.1",
            listen_port=9000,
        )
        assert node.info.http_url == "http://127.0.0.1:9000"
        assert node.info.ws_url == "ws://127.0.0.1:9000/p2p/ws"

    def test_advertise_host_overrides(self):
        from src.p2p.node import PeerNode
        node = PeerNode(
            capabilities={Capability.STORE},
            listen_host="0.0.0.0",
            listen_port=9000,
            advertise_host="store-node",
        )
        assert node.info.http_url == "http://store-node:9000"
        assert node.info.ws_url == "ws://store-node:9000/p2p/ws"
        # Listen host stays as bind address
        assert node.listen_host == "0.0.0.0"


class TestNodeDispatch:
    """Test PeerNode.handle_envelope dispatch without starting the server."""

    @pytest.fixture
    def node(self):
        from src.p2p.node import PeerNode
        return PeerNode(
            capabilities={Capability.STORE, Capability.LLM},
            listen_host="127.0.0.1",
            listen_port=19990,
            node_id="test-node",
        )

    async def test_handle_ping(self, node):
        env = Envelope(msg_type="ping", sender_id="other")
        response = await node.handle_envelope(env)
        assert response is not None
        assert response.msg_type == "pong"
        assert response.reply_to == env.msg_id

    async def test_handle_join(self, node):
        joiner = PeerInfo(
            node_id="joiner",
            capabilities=frozenset({Capability.INFERENCE}),
            http_url="http://localhost:9001",
            ws_url="ws://localhost:9001/p2p/ws",
        )
        env = Envelope(
            msg_type="join",
            sender_id="joiner",
            payload={"peer_info": joiner.to_dict()},
        )
        response = await node.handle_envelope(env)
        assert response is not None
        assert response.msg_type == "welcome"
        # The joiner should now be in the routing table
        assert node.routing.peer_count == 1

    async def test_handle_leave(self, node):
        # First add a peer
        info = PeerInfo(
            node_id="leaver",
            capabilities=frozenset({Capability.INFERENCE}),
            http_url="http://localhost:9001",
            ws_url="ws://localhost:9001/p2p/ws",
        )
        node.routing.update_peer(PeerState(info=info, status="alive", last_seen=time.time()))
        assert node.routing.peer_count == 1

        env = Envelope(msg_type="leave", sender_id="leaver")
        await node.handle_envelope(env)
        assert node.routing.peer_count == 0

    async def test_handle_gossip(self, node):
        peer_info = PeerInfo(
            node_id="gossip-peer",
            capabilities=frozenset({Capability.VALIDATION}),
            http_url="http://localhost:9002",
            ws_url="ws://localhost:9002/p2p/ws",
        )
        peer_state = PeerState(
            info=peer_info, status="alive", last_seen=time.time(), heartbeat_seq=5
        )
        env = Envelope(
            msg_type="gossip",
            sender_id="gossip-peer",
            payload={"peer_states": [peer_state.to_dict()]},
        )
        result = await node.handle_envelope(env)
        assert result is None  # gossip has no response
        assert node.routing.peer_count == 1

    async def test_dedup(self, node):
        env = Envelope(msg_type="ping", sender_id="other", msg_id="fixed-id")
        resp1 = await node.handle_envelope(env)
        assert resp1 is not None  # first time: handled

        resp2 = await node.handle_envelope(env)
        assert resp2 is None  # second time: deduped

    async def test_handle_request_without_memory_service(self, node):
        env = Envelope(
            msg_type="request",
            sender_id="other",
            payload={"method": "observe", "args": {"text": "hello", "source": "test"}},
        )
        response = await node.handle_envelope(env)
        assert response is not None
        assert response.msg_type == "response"
        assert response.payload["error"] is not None  # no MemoryService registered

    async def test_handle_request_missing_capability(self, node):
        # Create a node without STORE capability
        from src.p2p.node import PeerNode
        inference_node = PeerNode(
            capabilities={Capability.INFERENCE},
            listen_host="127.0.0.1",
            listen_port=19991,
            node_id="inference-only",
        )
        env = Envelope(
            msg_type="request",
            sender_id="other",
            payload={"method": "observe", "args": {"text": "hello", "source": "test"}},
        )
        response = await inference_node.handle_envelope(env)
        assert response.payload["error"] is not None
        assert "lacks capabilities" in response.payload["error"]

    async def test_event_listener_called(self, node):
        received = []

        async def listener(event_type, data):
            received.append((event_type, data))

        node.add_event_listener(listener)

        env = Envelope(
            msg_type="event",
            sender_id="other",
            ttl=1,  # don't re-broadcast
            payload={"event_type": "observe", "data": {"id": "obs-1"}},
        )
        await node.handle_envelope(env)
        assert len(received) == 1
        assert received[0] == ("observe", {"id": "obs-1"})


# ── P2PMemoryClient ────────────────────────────────────────────────


class TestP2PMemoryClient:
    """Test local execution path of P2PMemoryClient (no network)."""

    @pytest.fixture
    def client_with_mock_memory(self):
        from src.p2p.node import PeerNode
        from src.p2p.memory_client import P2PMemoryClient

        node = PeerNode(
            capabilities={Capability.STORE, Capability.LLM},
            listen_host="127.0.0.1",
            listen_port=19992,
            node_id="local-node",
        )

        class MockMemory:
            async def observe(self, text, source):
                return "obs-123"

            async def claim(self, text, source):
                return "claim-456"

            async def remember(self, query):
                return "the answer is 42"

            async def infer(self, observation_text):
                return "inferred claim"

            async def get_recent_observations(self, limit=10):
                return [{"id": "obs-1", "raw_content": "hello"}]

            async def get_recent_claims(self, limit=20):
                return []

            async def get_unresolved_contradictions(self):
                return []

            async def get_entities(self):
                return [{"id": "e-1", "name": "test"}]

            async def clear(self):
                pass

        node.register_service("memory", MockMemory())
        return P2PMemoryClient(node)

    async def test_observe_local(self, client_with_mock_memory):
        result = await client_with_mock_memory.observe("hello", source="test")
        assert result == "obs-123"

    async def test_claim_local(self, client_with_mock_memory):
        result = await client_with_mock_memory.claim("test claim", source="test")
        assert result == "claim-456"

    async def test_remember_local(self, client_with_mock_memory):
        result = await client_with_mock_memory.remember("what?")
        assert result == "the answer is 42"

    async def test_infer_local(self, client_with_mock_memory):
        result = await client_with_mock_memory.infer("observation text")
        assert result == "inferred claim"

    async def test_get_recent_observations_local(self, client_with_mock_memory):
        result = await client_with_mock_memory.get_recent_observations()
        assert len(result) == 1

    async def test_get_entities_local(self, client_with_mock_memory):
        result = await client_with_mock_memory.get_entities()
        assert len(result) == 1

    async def test_clear_local(self, client_with_mock_memory):
        await client_with_mock_memory.clear()  # should not raise

    async def test_remote_call_fails_without_peers(self):
        from src.p2p.node import PeerNode
        from src.p2p.memory_client import P2PMemoryClient

        node = PeerNode(
            capabilities={Capability.INFERENCE},  # no STORE or LLM
            listen_host="127.0.0.1",
            listen_port=19993,
            node_id="lonely-node",
        )
        client = P2PMemoryClient(node)
        with pytest.raises(RuntimeError, match="No peer available"):
            await client.observe("hello", source="test")


# ── WorkerAgent ─────────────────────────────────────────────────────


class TestWorkerAgent:
    async def test_event_wakeup(self):
        """Agent wakes up when on_network_event is called."""
        from src.agents.base import WorkerAgent

        class TestAgent(WorkerAgent):
            def __init__(self):
                # Minimal mock memory
                class MockMem:
                    async def claim(self, text, source):
                        return "c-1"
                super().__init__(
                    source_id="test", memory=MockMem(),
                    poll_interval=999,  # very long poll so event must wake it
                    agent_type="test",
                )
                self.process_count = 0

            def event_types(self):
                return ["observe"]

            async def process(self):
                self.process_count += 1
                self.stop()  # stop after first process
                return []

        agent = TestAgent()
        task = asyncio.create_task(agent.run())

        # Give the agent a moment to start and enter the wait
        await asyncio.sleep(0.1)
        await agent.on_network_event("observe", {"id": "obs-1"})

        await asyncio.wait_for(task, timeout=5.0)
        # process() called at least once on startup + once from event
        assert agent.process_count >= 1


# ── URL Override Tests ───────────────────────────────────────────


class TestUrlOverrides:
    """Test bootstrap URL remapping for cross-network scenarios."""

    def test_apply_url_overrides(self):
        from src.p2p.node import PeerNode

        node = PeerNode(
            capabilities={Capability.CLI},
            listen_host="127.0.0.1",
            listen_port=9003,
        )
        # Simulate a bootstrap override (Docker hostname -> localhost)
        node._url_overrides["store-node-id"] = (
            "http://localhost:9000",
            "ws://localhost:9000/p2p/ws",
        )

        peer = PeerState(
            info=PeerInfo(
                node_id="store-node-id",
                capabilities=frozenset({Capability.STORE, Capability.LLM}),
                http_url="http://store-node:9000",
                ws_url="ws://store-node:9000/p2p/ws",
                started_at=time.time(),
            ),
            status="alive",
            last_seen=time.time(),
            heartbeat_seq=5,
        )
        node.apply_url_overrides(peer)
        assert peer.info.http_url == "http://localhost:9000"
        assert peer.info.ws_url == "ws://localhost:9000/p2p/ws"

    def test_no_override_when_not_needed(self):
        from src.p2p.node import PeerNode

        node = PeerNode(
            capabilities={Capability.CLI},
            listen_host="127.0.0.1",
            listen_port=9003,
        )
        # No overrides set
        peer = PeerState(
            info=PeerInfo(
                node_id="some-node",
                capabilities=frozenset({Capability.INFERENCE}),
                http_url="http://inference-node:9000",
                ws_url="ws://inference-node:9000/p2p/ws",
                started_at=time.time(),
            ),
            status="alive",
            last_seen=time.time(),
            heartbeat_seq=1,
        )
        node.apply_url_overrides(peer)
        # Unchanged — no override for this peer
        assert peer.info.http_url == "http://inference-node:9000"

    def test_gossip_preserves_overrides(self):
        """Gossip should re-apply URL overrides so they don't get reset."""
        from src.p2p.node import PeerNode

        node = PeerNode(
            capabilities={Capability.CLI},
            listen_host="127.0.0.1",
            listen_port=9003,
        )
        node._url_overrides["store-abc"] = (
            "http://localhost:9000",
            "ws://localhost:9000/p2p/ws",
        )

        # Simulate gossip arriving with Docker-internal URLs
        gossip_envelope = Envelope(
            msg_type="gossip",
            sender_id="store-abc",
            payload={
                "peer_states": [
                    PeerState(
                        info=PeerInfo(
                            node_id="store-abc",
                            capabilities=frozenset({Capability.STORE, Capability.LLM}),
                            http_url="http://store-node:9000",
                            ws_url="ws://store-node:9000/p2p/ws",
                            started_at=time.time(),
                        ),
                        status="alive",
                        last_seen=time.time(),
                        heartbeat_seq=10,
                    ).to_dict(),
                ],
            },
        )
        node.gossip.handle_gossip(gossip_envelope)

        # The routing table should have the overridden URL
        peer = node.routing._peers.get("store-abc")
        assert peer is not None
        assert peer.info.http_url == "http://localhost:9000"
        assert peer.info.ws_url == "ws://localhost:9000/p2p/ws"
