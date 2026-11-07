# Third-party notices

## autoresearch skill

`research/.agents/skills/autoresearch/` is adapted from
[`uditgoenka/autoresearch`](https://github.com/uditgoenka/autoresearch), which
is distributed under the MIT License. Its original copyright notice is kept in
that directory's `LICENSE` file.

The research loop and `research/program.md` are adapted from Andrej Karpathy's
[`autoresearch`](https://github.com/karpathy/autoresearch). Its README declares
an MIT license. The upstream repository does not provide a separate license
file; consult its README for the upstream license declaration.

## Dependencies

When distributing built artifacts that include third-party dependencies, keep
the applicable dependency license and notice texts with the distribution. The
lockfiles and package manifests identify the versions; this file is not a
complete software bill of materials.

CI includes the complete dependency notices in `THIRD_PARTY_LICENSES.txt` with
the web, landing, and router artifacts. The Lambda source packages include the
project's `LICENSE`.

Notable direct dependency licenses include MIT (React, React Router, Vite,
Vitest, Tailwind CSS, TanStack Query), Apache-2.0 (TypeScript and AWS SDK
components), ISC (Lucide React), BSD-style (coder/websocket and
modernc.org/sqlite), and the mixed Apache-2.0 / modified MIT terms documented
by `aws-lambda-go`.
