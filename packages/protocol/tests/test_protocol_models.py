from __future__ import annotations

from unittest import TestCase

from seagull_protocol import (
    ActionRequest,
    AgentProfile,
    Delivery,
    DeliveryState,
    Handle,
    HookRuntime,
    HookType,
    Message,
    MessageRef,
    MessageIntent,
    ProtocolError,
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
