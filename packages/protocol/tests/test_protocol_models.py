from __future__ import annotations

import json
from unittest import TestCase

from seagull_protocol import (
    ActionRequest,
    AgentProfile,
    ContactExplanation,
    ContentRef,
    ContextBudget,
    ContextPack,
    Delivery,
    DeliveryState,
    Handle,
    HookRuntime,
    HookType,
    Message,
    MessageRef,
    MessageIntent,
    PayloadAccessScope,
    PayloadChunk,
    PayloadCompression,
    PayloadManifest,
    PayloadRetentionState,
    PayloadStorageProvider,
    ProtocolError,
    RelationshipPreset,
    StreamEvent,
    StreamEventType,
    TASK_LIFECYCLE_TRANSITIONS,
    TaskCreditLedgerEntry,
    TaskCreditLedgerEntryType,
    TaskEscrow,
    TaskQuote,
    TaskRequest,
    TaskResult,
    TaskState,
    TaskToolRequest,
    ToolGrant,
    Visibility,
    WorkflowTraceEntry,
    normalize_handle,
    normalize_relationship_preset,
    normalize_task_state,
    relationship_preset_defaults,
    task_lifecycle_allows,
    task_lifecycle_next_states,
)
from seagull_protocol.events import StreamEvent as EventStreamEvent
from seagull_protocol.work import TaskRequest as WorkTaskRequest


class ProtocolModelsTest(TestCase):
    def test_handle_normalizes_and_splits_address(self) -> None:
        handle = Handle(" @Researcher:Seagull.Local ")

        self.assertEqual("@researcher:seagull.local", str(handle))
        self.assertEqual("researcher", handle.local_part)
        self.assertEqual("seagull.local", handle.server)

    def test_invalid_handle_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            normalize_handle("researcher")

    def test_message_profile_shape(self) -> None:
        sender = Handle("@researcher:seagull.local")
        recipient = Handle("@reviewer:seagull.local")
        profile = AgentProfile(
            handle=recipient,
            display_name="Reviewer",
            capabilities=("review",),
            relationship_posture="trusted_reviewer",
            approval_required_for=("private_context", "tool_use"),
            allowed_use_terms=("inspect_shared_context", "return_artifacts"),
            contact_explanation="Requested because this agent reviews frontend plans.",
            protocols=("seagull", "a2a"),
            owner_user_id="user_1",
            node_id="node_1",
            trust_label="trusted",
            supported_extension_namespaces=("work.v1",),
        )
        message = Message(
            message_id="message_1",
            thread_id="thread_1",
            sender=sender,
            recipients=(recipient,),
            intent=MessageIntent.MESSAGE,
            visibility=Visibility.DIRECT,
            content="Please review this.",
        )

        self.assertEqual("@reviewer:seagull.local", str(profile.handle))
        self.assertEqual("trusted_reviewer", profile.relationship_posture)
        self.assertEqual(("private_context", "tool_use"), profile.approval_required_for)
        self.assertEqual(("inspect_shared_context", "return_artifacts"), profile.allowed_use_terms)
        self.assertEqual("Requested because this agent reviews frontend plans.", profile.contact_explanation)
        self.assertEqual(("seagull", "a2a"), profile.protocols)
        self.assertEqual("user_1", profile.owner_user_id)
        self.assertEqual("node_1", profile.node_id)
        self.assertEqual("trusted", profile.trust_label)
        self.assertEqual(("work.v1",), profile.supported_extension_namespaces)
        self.assertFalse(hasattr(profile, "mcp_server_url"))
        self.assertFalse(hasattr(profile, "private_prompt"))
        self.assertFalse(hasattr(profile, "tool_credentials"))
        self.assertEqual((recipient,), message.recipients)

    def test_relationship_presets_define_policy_defaults(self) -> None:
        trusted = relationship_preset_defaults(RelationshipPreset.TRUSTED_REVIEWER)
        blocked = relationship_preset_defaults("blocked")
        paid = relationship_preset_defaults("paid_worker")

        self.assertEqual("trusted", trusted.trust_label)
        self.assertEqual(("inspect_shared_context", "return_feedback", "return_artifacts"), trusted.allowed_use_terms)
        self.assertEqual("blocked", blocked.trust_label)
        self.assertEqual((), blocked.allowed_use_terms)
        self.assertIn("contact", blocked.approval_required_for)
        self.assertIn("paid_work", paid.approval_required_for)
        self.assertEqual(RelationshipPreset.SUMMARY_HELPER, normalize_relationship_preset("summary_helper"))
        with self.assertRaises(ProtocolError):
            normalize_relationship_preset("trusted")

    def test_contact_explanation_normalizes_relationship_and_handles(self) -> None:
        explanation = ContactExplanation(
            explanation_id="contact_explanation_delivery_1",
            delivery_id="delivery_1",
            message_id="message_1",
            thread_id="thread_1",
            requester="@Researcher:Seagull.Local",
            recipient=Handle("@reviewer:seagull.local"),
            answering_asset="@Reviewer:Seagull.Local",
            relationship="summary_helper",
            reason="task request",
            allowed_reason="Safety approved and relationship routes through review.",
            shared_context_summary="Review the attached plan.",
            shared_context_refs=("payload://thread_1/message_1/full",),
            pending_action="human review",
            current_stage="human.review",
            policy_refs=("message_safety:approved",),
            audit_event_refs=("delivery:delivery_1:needs_review",),
        )

        self.assertEqual("@researcher:seagull.local", str(explanation.requester))
        self.assertEqual("@reviewer:seagull.local", str(explanation.answering_asset))
        self.assertEqual("summary_helper", explanation.relationship)
        self.assertEqual(("payload://thread_1/message_1/full",), explanation.shared_context_refs)
        self.assertEqual("human review", explanation.pending_action)
        with self.assertRaises(ProtocolError):
            ContactExplanation(
                explanation_id="contact_explanation_delivery_1",
                delivery_id="delivery_1",
                message_id="message_1",
                thread_id="thread_1",
                requester="@researcher:seagull.local",
                recipient="@reviewer:seagull.local",
                answering_asset="@reviewer:seagull.local",
                relationship="friend",
            )

    def test_message_intent_supports_known_task_intents_and_extensions(self) -> None:
        message = Message(
            message_id="message_1",
            thread_id="thread_1",
            sender=Handle("@researcher:seagull.local"),
            recipients=(Handle("@reviewer:seagull.local"),),
            intent="vendor.custom_intent",
            visibility=Visibility.DIRECT,
            content="Custom extension event.",
        )

        self.assertEqual("task_request", MessageIntent.TASK_REQUEST.value)
        self.assertEqual("task_result", MessageIntent.TASK_RESULT.value)
        self.assertEqual("vendor.custom_intent", message.intent)

    def test_lifecycle_delivery_shape_keeps_current_copy_and_trace(self) -> None:
        sender = Handle("@researcher:seagull.local")
        recipient = Handle("@map-reader:seagull.local")
        ref = MessageRef(
            type="url",
            url="https://maps.google.com/example",
            find="identify_place",
            remember_as="possible meeting place",
        )
        trace = WorkflowTraceEntry(
            hook=HookType.RECEIVE_BEFORE,
            runtime=HookRuntime.CLOUD_NODE,
            actor=recipient,
            changed=("current_content", "refs"),
        )
        action = ActionRequest(
            action_request_id="action_1",
            type="open_url",
            target=ref.url,
            runtime=HookRuntime.CLOUD_NODE,
        )

        delivery = Delivery(
            delivery_id="delivery_1",
            message_id="message_1",
            thread_id="thread_1",
            sender=sender,
            recipient=recipient,
            state=DeliveryState.PENDING_ACTION,
            current_content="Can you check this map link?",
            refs=(ref,),
            workflow_trace=(trace,),
            current_stage="action.before",
            action_request=action,
        )

        self.assertEqual("https://maps.google.com/example", delivery.refs[0].url)
        self.assertEqual(HookType.RECEIVE_BEFORE, delivery.workflow_trace[0].hook)
        self.assertEqual("open_url", delivery.action_request.type)

    def test_content_ref_aligns_with_message_hub_string_fields(self) -> None:
        payload = ContentRef(
            content_ref="payload://thread_1/context/full",
            media_type="text/markdown",
            byte_length=4096,
            hash="sha256:abc123",
            compression=PayloadCompression.GZIP,
            compressed_byte_length=1024,
            compressed_hash="sha256:def456",
            retention_state=PayloadRetentionState.READY,
            access_scope=PayloadAccessScope.THREAD,
            fetch_policy_ref="policy://thread_1/payload_fetch",
        )
        message = Message(
            message_id="message_1",
            thread_id="thread_1",
            sender=Handle("@researcher:seagull.local"),
            recipients=(Handle("@reviewer:seagull.local"),),
            intent=MessageIntent.MESSAGE,
            visibility=Visibility.DIRECT,
            content_ref=payload.content_ref,
        )
        delivery = Delivery(
            delivery_id="delivery_1",
            message_id=message.message_id,
            thread_id=message.thread_id,
            sender=message.sender,
            recipient=message.recipients[0],
            state=DeliveryState.DELIVERED,
            current_content_ref=message.content_ref,
        )

        self.assertEqual("payload://thread_1/context/full", message.content_ref)
        self.assertEqual(message.content_ref, delivery.current_content_ref)
        self.assertEqual(PayloadCompression.GZIP, payload.compression)
        self.assertEqual(1024, payload.compressed_byte_length)
        self.assertEqual("sha256:def456", payload.compressed_hash)
        self.assertEqual("policy://thread_1/payload_fetch", payload.fetch_policy_ref)

    def test_payload_manifest_can_reference_chunks(self) -> None:
        payload = ContentRef(
            content_ref="payload://task_1/input",
            media_type="application/json",
            byte_length=12,
            hash="sha256:payload",
            compression=PayloadCompression.GZIP,
            compressed_byte_length=8,
            compressed_hash="sha256:compressed_payload",
            access_scope=PayloadAccessScope.THREAD,
            chunk_manifest_ref="manifest_1",
        )
        manifest = PayloadManifest(
            manifest_id="manifest_1",
            payload=payload,
            chunks=(
                PayloadChunk(
                    content_ref="payload://task_1/input/chunk/0",
                    sequence=0,
                    byte_offset=0,
                    byte_length=12,
                    hash="sha256:chunk",
                    compressed_byte_length=8,
                    compressed_hash="sha256:compressed_chunk",
                ),
            ),
            storage_provider=PayloadStorageProvider.LOCAL_NODE,
            storage_ref="local-node://payloads/payload_1",
        )

        self.assertEqual(payload.content_ref, manifest.payload.content_ref)
        self.assertEqual(PayloadStorageProvider.LOCAL_NODE, manifest.storage_provider)
        self.assertEqual("local-node://payloads/payload_1", manifest.storage_ref)
        self.assertEqual("payload://task_1/input/chunk/0", manifest.chunks[0].content_ref)
        self.assertEqual(8, manifest.chunks[0].compressed_byte_length)

    def test_payload_manifest_is_small_and_cloud_ready(self) -> None:
        payload = ContentRef(
            content_ref="payload://task_1/result",
            media_type="text/markdown",
            byte_length=9000,
            hash="sha256:plain",
            compression=PayloadCompression.GZIP,
            compressed_byte_length=3000,
            compressed_hash="sha256:gzip",
            retention_state=PayloadRetentionState.READY,
            access_scope=PayloadAccessScope.RECIPIENTS,
            fetch_policy_ref="policy://task_1/result_fetch",
        )
        manifest = PayloadManifest(
            manifest_id="manifest_1",
            payload=payload,
            storage_provider=PayloadStorageProvider.CLOUD_OBJECT,
            storage_ref="s3://seagull-dev-payloads/task_1/result.gz",
        )
        envelope = Message(
            message_id="message_1",
            thread_id="thread_1",
            sender=Handle("@researcher:seagull.local"),
            recipients=(Handle("@reviewer:seagull.local"),),
            intent=MessageIntent.TASK_RESULT,
            visibility=Visibility.DIRECT,
            content_ref=payload.content_ref,
        )
        manifest_wire = {
            "manifest_id": manifest.manifest_id,
            "content_ref": manifest.payload.content_ref,
            "media_type": manifest.payload.media_type,
            "byte_length": manifest.payload.byte_length,
            "hash": manifest.payload.hash,
            "compression": manifest.payload.compression.value,
            "compressed_byte_length": manifest.payload.compressed_byte_length,
            "compressed_hash": manifest.payload.compressed_hash,
            "ttl_expires_at": manifest.payload.ttl_expires_at,
            "retention_state": manifest.payload.retention_state.value,
            "access_scope": manifest.payload.access_scope.value,
            "fetch_policy_ref": manifest.payload.fetch_policy_ref,
            "storage_provider": manifest.storage_provider.value,
            "storage_ref": manifest.storage_ref,
            "chunks": [],
        }

        self.assertEqual("payload://task_1/result", envelope.content_ref)
        self.assertIsNone(envelope.content)
        self.assertEqual(PayloadStorageProvider.CLOUD_OBJECT, manifest.storage_provider)
        self.assertLess(len(json.dumps(manifest_wire, separators=(",", ":"))), 1000)

    def test_context_pack_carries_budgeted_context_without_inline_payload(self) -> None:
        payload = ContentRef(
            content_ref="payload://thread_1/artifact_1",
            media_type="application/pdf",
            byte_length=32000,
            hash="sha256:pdf",
        )
        recent = Message(
            message_id="message_1",
            thread_id="thread_1",
            sender=Handle("@researcher:seagull.local"),
            recipients=(Handle("@reviewer:seagull.local"),),
            intent=MessageIntent.MESSAGE,
            visibility=Visibility.DIRECT,
            content="Short visible context.",
        )
        pack = ContextPack(
            context_pack_id="context_pack_1",
            thread_id="thread_1",
            requester=Handle("@reviewer:seagull.local"),
            summary_ref="payload://thread_1/summary/latest",
            recent_messages=(recent,),
            selected_refs=(MessageRef(type="payload", url=payload.content_ref),),
            payload_refs=(payload,),
            allowed_recipients=(Handle("@researcher:seagull.local"),),
            policy_decision_id="policy_1",
            redacted_refs=("secret://token",),
            budget=ContextBudget(
                max_inline_chars=2000,
                max_recent_messages=10,
                max_payload_refs=5,
                token_budget_estimate=800,
            ),
        )

        self.assertEqual("payload://thread_1/summary/latest", pack.summary_ref)
        self.assertEqual((recent,), pack.recent_messages)
        self.assertEqual((payload,), pack.payload_refs)
        self.assertEqual(800, pack.budget.token_budget_estimate)
        self.assertTrue(pack.allows(Handle("@reviewer:seagull.local")))
        self.assertTrue(pack.allows(Handle("@researcher:seagull.local")))
        self.assertFalse(pack.allows(Handle("@outsider:seagull.local")))
        self.assertEqual(("secret://token",), pack.redacted_refs)

    def test_task_records_are_provider_neutral(self) -> None:
        request = TaskRequest(
            task_id="task_1",
            thread_id="thread_1",
            requester=Handle("@researcher:seagull.local"),
            recipient=Handle("@reviewer:seagull.local"),
            objective="Review the attached plan.",
            context_pack_id="context_pack_1",
            stream_id="stream_1",
            allowed_tool_names=("open_artifact",),
            allowed_use_terms=("no_memory",),
            tool_grant_ids=("grant_1",),
        )
        result = TaskResult(
            task_id=request.task_id,
            responder=request.recipient,
            state=TaskState.RESULT_READY,
            result_message_id="message_2",
            stream_id=request.stream_id,
            content_ref="payload://task_1/result",
            artifact_refs=("artifact_1",),
            tool_use_summary_refs=("artifact_tool_summary_1",),
        )
        grant = ToolGrant(
            grant_id="grant_1",
            task_id=request.task_id,
            issuer=request.requester,
            subject=request.recipient,
            audience="agent_a_mcp",
            scopes=("repo.read",),
            max_calls=10,
            allowed_resource_selectors=("docs/**",),
            approval_id="approval_1",
        )
        tool_request = TaskToolRequest(
            tool_request_id="tool_request_1",
            task_id=request.task_id,
            thread_id=request.thread_id,
            requester=request.requester,
            worker=request.recipient,
            tool_name="repo.read",
            purpose="Read only the files referenced by the task.",
            input_ref="payload://task_1/tool_request/input",
            approval_id="approval_1",
            policy_decision_id="policy_1",
            tool_grant_id=grant.grant_id,
            result_ref="payload://task_1/tool_request/result",
            artifact_refs=("artifact_tool_summary_1",),
            tool_use_summary_ref="payload://task_1/tool_summary",
        )
        quote = TaskQuote(
            quote_id="quote_1",
            task_id=request.task_id,
            thread_id=request.thread_id,
            requester=request.requester,
            worker=request.recipient,
            task_reason="Review private context using worker capacity.",
            expected_credit_cost=3,
            shared_context_refs=("thread://thread_1", "payload://task_1/input"),
            requires_approval=True,
            approval_reason="Paid private-context work requires owner approval.",
            limits_ref="seagull://tasks/task_1/limits",
            abuse_policy_ref="seagull://policies/task-credits/abuse-controls",
            audit_refs=("seagull://tasks/task_1/quotes/quote_1/audit",),
        )
        escrow = TaskEscrow(
            escrow_id="escrow_1",
            task_id=request.task_id,
            quote_id=quote.quote_id,
            thread_id=request.thread_id,
            requester=request.requester,
            worker=request.recipient,
            credit_amount=quote.expected_credit_cost,
            approval_id="approval_1",
            policy_decision_id="policy_1",
            limits_ref=quote.limits_ref,
            abuse_policy_ref=quote.abuse_policy_ref,
            audit_refs=("seagull://tasks/task_1/escrows/escrow_1/audit",),
        )
        ledger_entry = TaskCreditLedgerEntry(
            entry_id="task_credit_entry_1",
            account=request.requester,
            entry_type=TaskCreditLedgerEntryType.ESCROW_HOLD,
            credit_amount=quote.expected_credit_cost,
            available_delta=-quote.expected_credit_cost,
            escrow_delta=quote.expected_credit_cost,
            task_id=request.task_id,
            thread_id=request.thread_id,
            quote_id=quote.quote_id,
            escrow_id=escrow.escrow_id,
            counterparty=request.recipient,
            reason="Escrowed task credits.",
            policy_decision_id="policy_1",
            limits_ref=quote.limits_ref,
            abuse_policy_ref=quote.abuse_policy_ref,
            audit_refs=("seagull://tasks/task_1/escrows/escrow_1/audit",),
        )

        self.assertEqual(TaskState.REQUESTED, request.state)
        self.assertEqual(("open_artifact",), request.allowed_tool_names)
        self.assertEqual(("no_memory",), request.allowed_use_terms)
        self.assertEqual(("grant_1",), request.tool_grant_ids)
        self.assertEqual("stream_1", request.stream_id)
        self.assertEqual("stream_1", result.stream_id)
        self.assertEqual("payload://task_1/result", result.content_ref)
        self.assertEqual(("artifact_tool_summary_1",), result.tool_use_summary_refs)
        self.assertTrue(grant.read_only)
        self.assertEqual(("repo.read",), grant.scopes)
        self.assertEqual(("docs/**",), grant.allowed_resource_selectors)
        self.assertEqual("grant_1", tool_request.tool_grant_id)
        self.assertEqual(TaskState.NEEDS_APPROVAL, tool_request.state)
        self.assertEqual("policy_1", tool_request.policy_decision_id)
        self.assertEqual("payload://task_1/tool_request/result", tool_request.result_ref)
        self.assertEqual(3, quote.expected_credit_cost)
        self.assertEqual(("thread://thread_1", "payload://task_1/input"), quote.shared_context_refs)
        self.assertEqual("Paid private-context work requires owner approval.", quote.approval_reason)
        self.assertEqual(TaskState.ESCROWED, escrow.state)
        self.assertEqual(quote.expected_credit_cost, escrow.credit_amount)
        self.assertEqual(quote.limits_ref, escrow.limits_ref)
        self.assertEqual(quote.abuse_policy_ref, escrow.abuse_policy_ref)
        self.assertEqual(TaskCreditLedgerEntryType.ESCROW_HOLD, ledger_entry.entry_type)
        self.assertEqual(-3, ledger_entry.available_delta)
        self.assertEqual(3, ledger_entry.escrow_delta)
        self.assertEqual("internal_product_credit", ledger_entry.settlement_scope)

    def test_task_lifecycle_defines_credit_state_transitions(self) -> None:
        expected_states = {
            "requested",
            "quoted",
            "needs_approval",
            "approved",
            "escrowed",
            "accepted",
            "running",
            "result_ready",
            "result_accepted",
            "released",
            "completed",
            "canceled",
            "disputed",
            "refused",
            "failed",
        }
        self.assertTrue(expected_states.issubset({state.value for state in TaskState}))
        self.assertEqual(TaskState.QUOTED, normalize_task_state(" quoted "))
        quoted_request = TaskRequest(
            task_id="task_quoted",
            thread_id="thread_1",
            requester=Handle("@researcher:seagull.local"),
            recipient=Handle("@reviewer:seagull.local"),
            objective="Quote this task.",
            state="quoted",
        )
        self.assertEqual(TaskState.QUOTED, quoted_request.state)

        credit_path = (
            TaskState.REQUESTED,
            TaskState.QUOTED,
            TaskState.NEEDS_APPROVAL,
            TaskState.APPROVED,
            TaskState.ESCROWED,
            TaskState.ACCEPTED,
            TaskState.RUNNING,
            TaskState.RESULT_READY,
            TaskState.RESULT_ACCEPTED,
            TaskState.RELEASED,
            TaskState.COMPLETED,
        )
        for current, next_state in zip(credit_path, credit_path[1:]):
            self.assertTrue(task_lifecycle_allows(current, next_state))

        self.assertIn(TaskState.NEEDS_APPROVAL, TASK_LIFECYCLE_TRANSITIONS[TaskState.REQUESTED])
        self.assertIn(TaskState.DISPUTED, task_lifecycle_next_states(TaskState.RESULT_READY))
        self.assertIn(TaskState.CANCELED, task_lifecycle_next_states(TaskState.DISPUTED))
        self.assertEqual((), task_lifecycle_next_states(TaskState.COMPLETED))
        with self.assertRaises(ProtocolError):
            normalize_task_state("unknown")

    def test_stream_event_reserves_future_resume_and_final_message_fields(self) -> None:
        event = StreamEvent(
            stream_id="stream_1",
            sequence=3,
            event_type=StreamEventType.COMPLETED,
            subject_type="task",
            subject_id="task_1",
            resume_after=2,
            final_message_id="message_2",
            content_ref="payload://task_1/final",
        )

        self.assertEqual(StreamEventType.COMPLETED, event.event_type)
        self.assertEqual("task", event.subject_type)
        self.assertEqual("task_1", event.subject_id)
        self.assertEqual(2, event.resume_after)
        self.assertEqual("message_2", event.final_message_id)
        self.assertIs(EventStreamEvent, StreamEvent)
        self.assertIs(WorkTaskRequest, TaskRequest)

    def test_payload_and_stream_validation_rejects_invalid_values(self) -> None:
        with self.assertRaises(ProtocolError):
            ContentRef(
                content_ref="payload://bad",
                media_type="text/plain",
                byte_length=-1,
                hash="sha256:bad",
            )

        with self.assertRaises(ProtocolError):
            ContentRef(
                content_ref="payload://bad",
                media_type="text/plain",
                byte_length=12,
                hash="sha256:bad",
                compressed_byte_length=-1,
            )

        with self.assertRaises(ProtocolError):
            PayloadManifest(
                manifest_id="manifest_1",
                payload=ContentRef(
                    content_ref="payload://bad",
                    media_type="text/plain",
                    byte_length=12,
                    hash="sha256:bad",
                ),
                storage_ref=" ",
            )

        with self.assertRaises(ProtocolError):
            StreamEvent(
                stream_id="stream_1",
                sequence=-1,
                event_type=StreamEventType.DELTA,
                subject_type="task",
                subject_id="task_1",
            )

        with self.assertRaises(ProtocolError):
            ToolGrant(
                grant_id="grant_1",
                task_id="task_1",
                issuer=Handle("@researcher:seagull.local"),
                subject=Handle("@reviewer:seagull.local"),
                audience="agent_a_mcp",
                scopes=(),
            )
