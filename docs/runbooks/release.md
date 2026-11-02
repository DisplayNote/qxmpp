# Release

## Which branch ships

| Branch | Content | Shipped to Montage? |
|---|---|---|
| `1.6` | Upstream 1.6.1 (`project(qxmpp VERSION 1.6.1)`) + 29 DisplayNote commits (including PR merges); DisplayNote tags `v1.6.2`–`v1.6.5` | Yes — `conanfile.py` and `ci/azure-pipelines.yml` live here |
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
- **Templates**: repository resource `ci` = `DisplayNote/qt-conan-ci` at tag `2.4.0`, variable
  group `montage-client-environment-variables`. Stages and templates used:
  - `common/setup.yml@ci` (the `setup` stage; its check run is `VERSION ReadVersion`);
  - `macos_x86_64`, `macos_arm64` (`macos-15`, Xcode 26.2, Qt artifact `qt-mac-desktop-6.8.8`),
    `ios_arm64` (`qt-mac-ios-6.8.8` 1.0.1): `common/python.yml`, `common/conan/config.yml`,
    `common/xcode.yml`, `common/qt.yml`, `common/build-unix.yml` (CMake + Ninja);
  - `android_arm64_v8a`, `android_armv7`, `android_x86_64` (pool `agent-pool-ubuntu2204-vmss`,
    `qt-linux-android-6.8.8`, NDK `28.2.13676358`, `ANDROID_PLATFORM=android-28`): same templates
    plus `common/ndk.yml`;
  - `windows-x86_64/build.yml@ci` (MSVC 2022 x64 Qt kit);
  - `common/deploy-develop.yml@ci` with `packageName: 'qxmpp'`, `conanfile: 'qxmpp/conanfile.py'`
    and the profiles `msvc19.x86_64`, `macos.x86_64`, `macos.arm64`, `ios.arm64`,
    `android.arm64-v8a`, `android.armeabi-v7a`, `android.x86_64`.
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

Observed from the history: changes land on `1.6` through GitHub PRs (`Merge pull request #N
from DisplayNote/<branch>`), then a `v1.6.<n>` tag is pushed on the merge commit (e.g. `v1.6.5`
on `d51f9ef9`), which triggers the pipeline and its deploy stage. `project(... VERSION ...)` in
`CMakeLists.txt` has stayed at `1.6.1`. Bumping the dependency in Montage happens in Montage,
not here.

## Taking a newer upstream release

Upstream releases bump `project(... VERSION ...)`, add a `CHANGELOG.md` section and tag
`vX.Y.Z`. Moving DisplayNote to a newer upstream line means re-applying the DisplayNote commits
(`git log origin/master..origin/1.6`) onto it, including the reconnection and resumption
changes listed in [../modules/client.md](../modules/client.md).
