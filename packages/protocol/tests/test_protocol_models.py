from __future__ import annotations

from unittest import TestCase

from seagull_protocol import (
    ActionRequest,
    AgentProfile,
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
    ProtocolError,
    StreamEvent,
    StreamEventType,
    TaskRequest,
    TaskResult,
    TaskState,
    Visibility,
    WorkflowTraceEntry,
    normalize_handle,
)


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
            protocols=("seagull", "a2a"),
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
        self.assertEqual(("seagull", "a2a"), profile.protocols)
        self.assertEqual((recipient,), message.recipients)

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
            retention_state=PayloadRetentionState.READY,
            access_scope=PayloadAccessScope.THREAD,
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

    def test_payload_manifest_can_reference_chunks(self) -> None:
        payload = ContentRef(
            content_ref="payload://task_1/input",
            media_type="application/json",
            byte_length=12,
            hash="sha256:payload",
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
                ),
            ),
        )

        self.assertEqual(payload.content_ref, manifest.payload.content_ref)
        self.assertEqual("payload://task_1/input/chunk/0", manifest.chunks[0].content_ref)

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

    def test_task_records_are_provider_neutral(self) -> None:
        request = TaskRequest(
            task_id="task_1",
            thread_id="thread_1",
            requester=Handle("@researcher:seagull.local"),
            recipient=Handle("@reviewer:seagull.local"),
            objective="Review the attached plan.",
            context_pack_id="context_pack_1",
            allowed_tool_names=("open_artifact",),
        )
        result = TaskResult(
            task_id=request.task_id,
            responder=request.recipient,
            state=TaskState.RESULT_READY,
            result_message_id="message_2",
            content_ref="payload://task_1/result",
            artifact_refs=("artifact_1",),
        )

        self.assertEqual(TaskState.REQUESTED, request.state)
        self.assertEqual(("open_artifact",), request.allowed_tool_names)
        self.assertEqual("payload://task_1/result", result.content_ref)

    def test_stream_event_reserves_future_resume_and_final_message_fields(self) -> None:
        event = StreamEvent(
            stream_id="stream_1",
            sequence=3,
            event_type=StreamEventType.COMPLETED,
            task_id="task_1",
            resume_after=2,
            final_message_id="message_2",
            content_ref="payload://task_1/final",
        )

        self.assertEqual(StreamEventType.COMPLETED, event.event_type)
        self.assertEqual(2, event.resume_after)
        self.assertEqual("message_2", event.final_message_id)

    def test_payload_and_stream_validation_rejects_invalid_values(self) -> None:
        with self.assertRaises(ProtocolError):
            ContentRef(
                content_ref="payload://bad",
                media_type="text/plain",
                byte_length=-1,
                hash="sha256:bad",
            )

        with self.assertRaises(ProtocolError):
            StreamEvent(
                stream_id="stream_1",
                sequence=-1,
                event_type=StreamEventType.DELTA,
            )
