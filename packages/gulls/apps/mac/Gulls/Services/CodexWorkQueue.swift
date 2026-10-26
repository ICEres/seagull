import Foundation

/// Scheduling is in memory; the work and execution records are durable in
/// CodexSessionDatabase. A failed or uncertain predecessor is never replayed.
enum CodexWorkQueue {
    static func next(in tasks: [CodexTask]) -> CodexTask? {
        let ordered = tasks.sorted {
            let left = $0.work?.queuedAt ?? $0.work?.createdAt ?? .distantFuture
            let right = $1.work?.queuedAt ?? $1.work?.createdAt ?? .distantFuture
            return left == right ? $0.id < $1.id : left < right
        }
        return ordered.first { task in
            guard task.execution?.status == .queued, let work = task.work,
                  work.publication == .ready, work.route == .embedded else { return false }
            return !ordered.contains { earlier in
                guard earlier.id != task.id, let state = earlier.execution?.status,
                      [.failed, .interrupted, .uncertain, .needsApproval, .starting, .working].contains(state) else { return false }
                let sameContext = earlier.work?.contextID == work.contextID
                let uncertainConversation = state == .uncertain && work.conversationKey != nil
                    && earlier.work?.conversationKey == work.conversationKey
                guard sameContext || uncertainConversation else { return false }
                if work.predecessorTaskID == earlier.id,
                   [.failed, .interrupted].contains(state) { return false }
                return (earlier.work?.createdAt ?? .distantPast) < work.createdAt
            }
        }
    }
}
