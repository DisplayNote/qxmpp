# Release

## Which branch ships

| Branch | Content | Shipped to Montage? |
|---|---|---|
| `1.6` | Upstream 1.6.1 (`project(qxmpp VERSION 1.6.1)`) + 29 DisplayNote commits (including PR merges); DisplayNote tags `v1.6.2`–`v1.6.6`, bare `1.6.<n>` from the next release | Yes — `conanfile.py` and `ci/azure-pipelines.yml` live here |
| `master` | Plain upstream QXmpp (`project(qxmpp VERSION 1.8.0)`), no DisplayNote commits | No |
| `1.3`–`1.5`, `1.7` | Upstream release branches | No |

Check with `git log --oneline origin/master..origin/1.6`.

Note: the `v1.6.1` tag on `origin` points at a DisplayNote commit (`7effca51`), not at
upstream's `Release QXmpp 1.6.1` commit; a clone that also fetched upstream tags may show the
upstream one locally.

## How a package is built (Azure Pipelines)

`ci/azure-pipelines.yml` runs in Azure Pipelines (check runs on GitHub appear as `qxmpp (…)`
from the `azure-pipelines` app):

- **Triggers**: every pushed tag (`trigger: tags: include: '*'`) and every non-draft PR to any
  branch, except PRs that only touch `doc`, `README.md`, `COPYING` or `LICENSES`. Plain branch
  pushes do not trigger it.
- **Templates**: repository resource `ci` = `DisplayNote/qt-conan-ci` at tag `2.8.1`,
  repository resource `dn-templates` = `DisplayNote/dn-pipeline-templates` at `refs/heads/main`,
  variable group `montage-client-environment-variables`. Stage order: `SecretScan` +
  `DependencyScan` (in parallel) → `setup` → `tests_coverage` → build stages → deploy; every
  dependency is explicit. Stages and templates used:
  - `secret-scan-stage.yml@dn-templates` (the `SecretScan` stage: gitleaks over the full
    history of the built ref, blocking; exceptions in `.gitleaks.toml` / `.gitleaksignore`);
  - `dependency-scan-stage.yml@dn-templates` (the `DependencyScan` stage: OSV-Scanner + Grype,
    blocking, `allowNoPackages: true`);
  - `common/setup.yml@ci` (the `setup` stage, `dependsOn: [SecretScan, DependencyScan]`; its
    check run is `VERSION ReadVersion`);
  - `windows-x86_64/coverage.yml@ci` (the `tests_coverage` stage: QXmpp's ctest suites under
    OpenCppCoverage, Windows Debug, audit mode `blocking: false`);
  - `macos_x86_64`, `macos_arm64` (`macos-15`, Xcode 26.2, Qt artifact `qt-mac-desktop-6.8.8`),
    `ios_arm64` (`qt-mac-ios-6.8.8` 1.0.1): `common/python.yml`, `common/conan/config.yml`,
    `common/xcode.yml`, `common/qt.yml`, `common/build-unix.yml` (CMake + Ninja);
  - `android_arm64_v8a`, `android_armv7`, `android_x86_64` (pool `agent-pool-ubuntu2204-vmss`,
    `qt-linux-android-6.8.8`, NDK `28.2.13676358`, `ANDROID_PLATFORM=android-28`): same templates
    plus `common/ndk.yml`;
  - `windows-x86_64/build.yml@ci` (MSVC 2022 x64 Qt kit);
  - `common/deploy-develop.yml@ci` with `packageName: 'qxmpp'`, `conanfile: 'qxmpp/conanfile.py'`,
    `bareTagsOnly: true` and the profiles `msvc19.x86_64`, `macos.x86_64`, `macos.arm64`,
    `ios.arm64`, `android.arm64-v8a`, `android.armeabi-v7a`, `android.x86_64`. The package
    version is the tag name, so only a tag that starts with a digit (`X.Y.Z`) deploys; any other
    tag, such as upstream-style `vX.Y.Z`, still builds but skips the deploy stage.
- **CMake arguments** for every platform (`cmakeCommonArgs`): `-DBUILD_SHARED=ON
  -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOCUMENTATION=OFF -DBUILD_UNVERSIONED_LIBRARY=ON`.
  Every platform is built in Debug and Release. There is no Linux desktop stage.
- **Staging**: each build is installed under `<Platform>/<BuildType>` (`Macos/<arch>/<BuildType>`
  and `Android/<arch>/<BuildType>`, with Conan's arch names `x86_64` / `armv8` / `armv7`) in the
  shared `build-folder` artifact.
- **Packaging**: `conanfile.py` (`QxmppConan`, Conan 1.x API) does not build; `package()` copies
  the staged tree for the profile's `os`/`arch`/`build_type` (`_source_folder()`) and raises
  `ConanException` if it is missing. `package_info()` collects the libraries from `lib/`.

What the templates do internally (how the version and channel are derived, where the package
is uploaded) lives in `DisplayNote/qt-conan-ci`, not in this repository.

## Manual equivalent

`README.md` "Building" documents per-platform commands for Win64 and macOS:
`cmake --install build --prefix <Platform>/<BuildType>` then
`conan export-pkg . qxmpp/1.6.1@dn/stable -pr <profile> -f` (the macOS example uses
`@dn/develop`). The library must stay shared (LGPL note in `README.md`).

## Cutting a DisplayNote release

Changes land on `1.6` through GitHub PRs (`Merge pull request #N from DisplayNote/<branch>`),
then a **bare** `1.6.<n>` tag (no `v`) is pushed on the merge commit, which triggers the
pipeline and its deploy stage and publishes `qxmpp/1.6.<n>@dn/develop`; promotion to
`dn/stable` is done by the release pipeline. `project(... VERSION ...)` in `CMakeLists.txt` has
stayed at `1.6.1`. Bumping the dependency in Montage happens in Montage, not here.

Releases up to `v1.6.6` were tagged with a `v` and published as `qxmpp/v1.6.<n>`. Consumers'
dependency scans cannot identify a Conan version that does not start with a digit (it fails
Montage's `DependencyScan`), so the deploy stage now runs only on bare tags
(`bareTagsOnly: true`) and the next release is the first `qxmpp/1.6.<n>`. The old
`v`-prefixed packages stay in the remote; Montage moves off them when it bumps to the first
bare release.

Bare tags are also a namespace upstream does not use. Upstream QXmpp tags every release
`vX.Y.Z` and has no bare tags, both on GitHub (`qxmpp-project/qxmpp`) and on KDE
(`invent.kde.org/libraries/qxmpp`, checked 2026-11-06). DisplayNote's `v1.6.2`–`v1.6.6` reuse
upstream's naming, and `v1.6.1` on `origin` already shadows upstream's own `v1.6.1` (see "Which
branch ships"). A bare `1.6.<n>` cannot be confused with an upstream release.

Every tag still triggers the pipeline (`trigger: tags: include: '*'`), so a `v`-tag runs the
scans, tests and every platform build; only the deploy stage is skipped. That also covers upstream
syncs: if upstream's `vX.Y.Z` tags are ever pushed to `origin` (for example `git push --tags`
after fetching upstream), they no longer publish a `qxmpp/vX.Y.Z` package.

## Taking a newer upstream release

Upstream releases bump `project(... VERSION ...)`, add a `CHANGELOG.md` section and tag
`vX.Y.Z`. Moving DisplayNote to a newer upstream line means re-applying the DisplayNote commits
(`git log origin/master..origin/1.6`) onto it, including the reconnection and resumption
changes listed in [../modules/client.md](../modules/client.md).
