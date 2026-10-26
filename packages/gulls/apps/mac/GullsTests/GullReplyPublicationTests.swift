import XCTest
@testable import Gulls

@MainActor
final class GullReplyPublicationTests: XCTestCase {
    private final class Tokens: GullsTokenStore {
        func token(for profileID: String) -> String? { nil }
        func legacyToken() -> String? { nil }
        @discardableResult func setToken(_ token: String, for profileID: String) -> Bool { true }
    }

    private func makeStore(profileID: String = "reply-test", replyCLI: GullsCLI? = nil) throws -> (CodexTaskStore, UserDefaults, URL) {
        let suite = "gull-reply-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let context = FileManager.default.temporaryDirectory.appendingPathComponent(suite, isDirectory: true)
        let config = GullsConfig(profileID: profileID, defaults: defaults, tokenStore: Tokens())
        config.apiURL = "https://messages.example.test"
        config.agentHandle = "@\(profileID):gulls.ai"
        config.contextDir = context.path
        config.token = "test-token"
        config.codexEnabled = true
        let store = CodexTaskStore(config: config, replyCLI: replyCLI)
        addTeardownBlock {
            defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: context)
        }
        return (store, defaults, context)
    }

    private func makeFakeCLI(mode: String = "success", logURL: URL? = nil) throws -> GullsCLI {
        let script = FileManager.default.temporaryDirectory
            .appendingPathComponent("gulls-reply-fixture-\(UUID().uuidString)")
        let log = logURL ?? script.appendingPathExtension("content")
        let commands = log.appendingPathExtension("commands")
        let source = """
        #!/usr/bin/python3
        import json, sys
        from pathlib import Path
        mode = \(String(reflecting: mode))
        log = Path(\(String(reflecting: log.path)))
        commands = Path(\(String(reflecting: commands.path)))
        args = sys.argv[1:]
        command = next(a for a in args if a in ('reply-publish', 'reply-status'))
        key = args[args.index('--publication-key') + 1]
        with commands.open('a') as f:
            f.write(command + chr(10))
        if command == 'reply-publish':
            content = Path(args[args.index('--content-file') + 1]).read_text()
            log.write_text(content)
            if mode in ('exit1', 'foundfalse'):
                sys.exit(1)
            if mode == 'exit3':
                sys.exit(3)
        if command == 'reply-status' and mode == 'foundfalse':
            print(json.dumps({'publication_key': key, 'found': False}))
            sys.exit(0)
        receipt = {'publication_key': key, 'found': True,
            'delivery': {'delivery_id': args[-1], 'status': 'replied'},
            'reply': {'message_id': 'message-transport', 'thread_id': 'thread-1',
                'message': {'content_inline': log.read_text(), 'created_at': '2026-10-26T00:00:00Z'}}}
        if mode == 'no-id':
            del receipt['reply']['message_id']
        print(json.dumps(receipt))
        """
        try Data(source.utf8).write(to: script, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
        addTeardownBlock {
            for file in [script, log, commands] { try? FileManager.default.removeItem(at: file) }
        }
        return GullsCLI(executableURL: script)
    }

    private func makeDelegatedTask(_ store: CodexTaskStore, deliveryID: String = "delivery-1") throws -> CodexTask {
        let root = URL(fileURLWithPath: store.config.contextDir, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        let source = root.appendingPathComponent("message.md")
        try Data("Untrusted message and private owner guidance.".utf8).write(to: source)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: source.path)
        let task = try store.create(
            goal: "Handle this message.", workingDirectory: nil,
            deliveryID: deliveryID, threadID: "thread-1", contextPath: source.path,
            sourceMessageID: "message-1", ownerRequestID: "owner-1",
            authorizeReply: true,
            cliExecutableURL: URL(fileURLWithPath: "/Applications/Gulls.app/Contents/Resources/gulls")
        )
        return try store.selectRoute(.external, for: task)
    }

    func testPrivateTasksDoNotReceiveReplyAuthorization() throws {
        let (store, _, _) = try makeStore()
        let task = try store.create(goal: "Private task", workingDirectory: nil,
                                    ownerRequestID: "owner-private",
                                    cliExecutableURL: URL(fileURLWithPath: "/tmp/gulls"))
        XCTAssertNil(task.request.replyAuthorizationID)
        XCTAssertNil(task.reply)
    }

    func testDelegatedSubmissionIsSeparateAndTakeoverRevokesIt() async throws {
        let (store, _, _) = try makeStore()
        let task = try makeDelegatedTask(store)
        XCTAssertNotNil(task.request.replyAuthorizationID)
        let submitted = try store.submitReply(content: "Exact public answer", for: task)
        XCTAssertEqual(submitted.content, "Exact public answer")
        XCTAssertEqual(submitted.status, .readyToSend)

        let current = try XCTUnwrap(store.latestTask(for: task.request.deliveryID!))
        let retained = try await store.takeOverReply(current)
        XCTAssertEqual(retained, "Exact public answer")
        store.refresh()
        let revoked = try XCTUnwrap(store.latestTask(for: task.request.deliveryID!)?.reply)
        XCTAssertEqual(revoked.status, .revoked)
        XCTAssertThrowsError(try store.submitReply(content: "Late answer", for: current))
    }

    func testSameSubmissionIsIdempotentButDifferentContentIsRejected() throws {
        let (store, _, _) = try makeStore()
        let task = try makeDelegatedTask(store, deliveryID: "idempotent")
        let first = try store.submitReply(content: "Stable answer", for: task)
        let replay = try store.submitReply(content: "Stable answer", for: task)
        XCTAssertEqual(first.publicationKey, replay.publicationKey)
        XCTAssertThrowsError(try store.submitReply(content: "Changed answer", for: task))
    }

    func testDisablingAutomaticDeliveryMovesReadyReplyToReviewAndDoesNotReenableIt() throws {
        let (store, _, _) = try makeStore()
        let task = try makeDelegatedTask(store, deliveryID: "delivery-policy")
        _ = try store.submitReply(content: "Needs review", for: task)
        try store.setSendRepliesAutomatically(false)
        store.refresh()
        let reviewed = try XCTUnwrap(store.latestTask(for: "delivery-policy")?.reply)
        XCTAssertEqual(reviewed.status, .needsReview)
        XCTAssertFalse(reviewed.automatic)

        try store.setSendRepliesAutomatically(true)
        store.refresh()
        let stillReviewed = try XCTUnwrap(store.latestTask(for: "delivery-policy")?.reply)
        XCTAssertEqual(stillReviewed.status, .needsReview)
    }

    func testDisabledPolicyBeforeSubmissionCreatesReviewOnlyReply() throws {
        let (store, _, _) = try makeStore()
        try store.setSendRepliesAutomatically(false)
        let task = try makeDelegatedTask(store, deliveryID: "review-first")
        let reply = try store.submitReply(content: "Manual approval", for: task)
        XCTAssertEqual(reply.status, .needsReview)
        XCTAssertFalse(reply.automatic)
    }

    func testRestartConvertsSendingReplyToUncertainWithoutMessageID() throws {
        let (store, _, _) = try makeStore()
        let task = try makeDelegatedTask(store, deliveryID: "restart-send")
        var reply = try store.submitReply(content: "May have sent", for: task)
        reply.status = .sending
        reply.deliveryUnresolved = true
        let databaseURL = store.tasksDirectory.appendingPathComponent("sessions.sqlite3")
        let database = try CodexSessionDatabase(url: databaseURL)
        try database.saveReply(reply)

        let restarted = CodexTaskStore(config: store.config)
        restarted.refresh()
        let recovered = try XCTUnwrap(restarted.latestTask(for: "restart-send")?.reply)
        XCTAssertEqual(recovered.status, .uncertain)
        XCTAssertNil(recovered.messageID)
        XCTAssertTrue(recovered.deliveryUnresolved)
    }

    func testApprovePublishesExactReplyAndRequiresReceiptMessageID() async throws {
        let logURL = FileManager.default.temporaryDirectory.appendingPathComponent("reply-content-\(UUID().uuidString)")
        let cli = try makeFakeCLI(logURL: logURL)
        let (store, _, _) = try makeStore(replyCLI: cli)
        store.config.sendRepliesAutomatically = false
        let task = try makeDelegatedTask(store, deliveryID: "delivery-transport")
        _ = try store.submitReply(content: "  Exact transport content\n", for: task)
        try await store.approveReply(task)
        store.refresh()
        let sent = try XCTUnwrap(store.latestTask(for: "delivery-transport")?.reply)
        XCTAssertEqual(sent.status, .sent)
        XCTAssertEqual(sent.messageID, "message-transport")
        XCTAssertEqual(try String(contentsOf: logURL), "  Exact transport content\n")
        XCTAssertEqual(try String(contentsOf: logURL.appendingPathExtension("commands")), "reply-publish\n")
    }

    func testAmbiguousPublishCanRecoverByStatusWithoutRepublishing() async throws {
        let log = FileManager.default.temporaryDirectory.appendingPathComponent("recover-\(UUID().uuidString)")
        let cli = try makeFakeCLI(mode: "exit1", logURL: log)
        let (store, _, _) = try makeStore(replyCLI: cli)
        store.config.sendRepliesAutomatically = false
        let task = try makeDelegatedTask(store, deliveryID: "delivery-recover")
        _ = try store.submitReply(content: "Recover me", for: task)
        do { try await store.approveReply(task); XCTFail("Expected an ambiguous publish failure") }
        catch { }
        store.refresh()
        let uncertain = try XCTUnwrap(store.latestTask(for: "delivery-recover")?.reply)
        XCTAssertEqual(uncertain.status, .uncertain)
        XCTAssertTrue(uncertain.deliveryUnresolved)

        let recoveryCLI = cli
        let recoveredStore = CodexTaskStore(config: store.config, replyCLI: recoveryCLI)
        let recoveredTask = try XCTUnwrap(recoveredStore.latestTask(for: "delivery-recover"))
        try await recoveredStore.checkReplyStatus(recoveredTask)
        recoveredStore.refresh()
        let sent = try XCTUnwrap(recoveredStore.latestTask(for: "delivery-recover")?.reply)
        XCTAssertEqual(sent.status, .sent)
        XCTAssertEqual(sent.messageID, "message-transport")
        XCTAssertEqual(try String(contentsOf: log.appendingPathExtension("commands")), "reply-publish\nreply-status\n")
    }

    func testMissingReceiptRequiresReviewAndCannotBeTakenOver() async throws {
        let cli = try makeFakeCLI(mode: "foundfalse")
        let (store, _, _) = try makeStore(replyCLI: cli)
        store.config.sendRepliesAutomatically = false
        let task = try makeDelegatedTask(store, deliveryID: "delivery-missing")
        _ = try store.submitReply(content: "Uncertain answer", for: task)
        do { try await store.approveReply(task); XCTFail("Expected an ambiguous publish failure") }
        catch { }

        let statusCLI = cli
        let checkedStore = CodexTaskStore(config: store.config, replyCLI: statusCLI)
        let checkedTask = try XCTUnwrap(checkedStore.latestTask(for: "delivery-missing"))
        try await checkedStore.checkReplyStatus(checkedTask)
        checkedStore.refresh()
        let review = try XCTUnwrap(checkedStore.latestTask(for: "delivery-missing")?.reply)
        XCTAssertEqual(review.status, .needsReview)
        XCTAssertTrue(review.deliveryUnresolved)
        do { _ = try await checkedStore.takeOverReply(checkedTask); XCTFail("Unresolved publication must not be taken over") }
        catch { }
    }

    func testDefinitiveRejectionFailsWithoutFallback() async throws {
        let cli = try makeFakeCLI(mode: "exit3")
        let (store, _, _) = try makeStore(replyCLI: cli)
        store.config.sendRepliesAutomatically = false
        let task = try makeDelegatedTask(store, deliveryID: "delivery-rejected")
        _ = try store.submitReply(content: "Rejected answer", for: task)
        do { try await store.approveReply(task); XCTFail("Expected definitive rejection") }
        catch { }
        store.refresh()
        let failed = try XCTUnwrap(store.latestTask(for: "delivery-rejected")?.reply)
        XCTAssertEqual(failed.status, .failed)
        XCTAssertFalse(failed.deliveryUnresolved)
    }

    func testMissingMessageIDCannotMarkReplySent() async throws {
        let cli = try makeFakeCLI(mode: "no-id")
        let (store, _, _) = try makeStore(replyCLI: cli)
        store.config.sendRepliesAutomatically = false
        let task = try makeDelegatedTask(store)
        _ = try store.submitReply(content: "Public reply", for: task)
        do { try await store.approveReply(task); XCTFail("A message ID is required") }
        catch { }
        let reply = try XCTUnwrap(store.tasks.first?.reply)
        XCTAssertEqual(reply.status, .uncertain)
        XCTAssertNil(reply.messageID)
    }

    func testAutomaticSubmissionPublishesOnceWithoutUsingComposer() async throws {
        let log = FileManager.default.temporaryDirectory.appendingPathComponent("automatic-\(UUID().uuidString)")
        let cli = try makeFakeCLI(logURL: log)
        let (store, _, _) = try makeStore(replyCLI: cli)
        let task = try makeDelegatedTask(store)
        _ = try store.submitReply(content: "Automatically submitted public answer", for: task)
        for _ in 0..<100 {
            if store.tasks.first?.reply?.status == .sent { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTAssertEqual(store.tasks.first?.reply?.status, .sent)
        XCTAssertNil(store.tasks.first?.result, "A private final result is not required to deliver an explicit reply")
        _ = try store.submitReply(content: "Automatically submitted public answer", for: task)
        store.refresh()
        XCTAssertEqual(try String(contentsOf: log.appendingPathExtension("commands")), "reply-publish\n")
    }

    func testOwnerDecisionRevokesPendingPublicationBeforeLateResult() async throws {
        let (store, _, _) = try makeStore()
        let task = try makeDelegatedTask(store)
        _ = try store.submitReply(content: "Unsent answer", for: task)
        try await store.prepareOwnerDecision(deliveryID: "delivery-1")
        XCTAssertEqual(store.tasks.first?.reply?.status, .revoked)
        XCTAssertThrowsError(try store.submitReply(content: "Late answer", for: task))
    }

    func testQuitKeepsUnsentPublicReplyForReview() throws {
        let (store, _, _) = try makeStore()
        let task = try makeDelegatedTask(store)
        _ = try store.submitReply(content: "Keep for review", for: task)
        store.suspendExecution(revokeReplies: false)
        let reopened = CodexTaskStore(config: store.config)
        XCTAssertEqual(reopened.tasks.first?.reply?.status, .needsReview)
        XCTAssertEqual(reopened.tasks.first?.reply?.content, "Keep for review")
        XCTAssertTrue(reopened.config.sendRepliesAutomatically, "Pausing does not change the Gull's preference for new tasks")
    }

    func testExternalReplyImportsOnlyExplicitBoundArtifact() throws {
        let (store, _, _) = try makeStore()
        let task = try makeDelegatedTask(store)
        let submission = GullReplySubmission(version: 1, taskID: task.id,
            profileID: task.request.profileID, gullHandle: task.request.gullHandle,
            connectionRevision: task.request.connectionRevision,
            requestSHA256: try XCTUnwrap(task.work?.requestDigest),
            authorizationID: try XCTUnwrap(task.request.replyAuthorizationID),
            content: "External public answer", submittedAt: "2026-10-26T00:00:00Z")
        let file = store.tasksDirectory.appendingPathComponent(task.id).appendingPathComponent("reply.json")
        try JSONEncoder().encode(submission).write(to: file)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        store.refresh()
        XCTAssertEqual(store.tasks.first?.reply?.content, "External public answer")
        XCTAssertEqual(store.tasks.first?.reply?.status, .readyToSend)
        XCTAssertNil(store.tasks.first?.result)
    }

    func testDifferentProfileCannotSubmitAnotherGullsReply() throws {
        let (store, _, _) = try makeStore(profileID: "one")
        let (other, _, _) = try makeStore(profileID: "two")
        let task = try makeDelegatedTask(store, deliveryID: "cross-profile")
        XCTAssertThrowsError(try other.submitReply(content: "Wrong Gull", for: task))
    }
}
