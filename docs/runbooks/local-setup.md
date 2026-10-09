# Local setup

From a clean machine to a built library with tests. Upstream build options are documented
in [README.md](../../README.md) ("Building (original)") and
[CONTRIBUTING.md](../../CONTRIBUTING.md); the DisplayNote packaging builds are in the
`README.md` "Building" section and [release.md](release.md).

## 1. Clone

```bash
git clone git@github.com:DisplayNote/qxmpp.git
cd qxmpp
git switch 1.6   # DisplayNote's packaged line; `master` (the GitHub default) is plain upstream
```

Run `/secret-scan-setup` once per clone (or `--global` once per machine for new clones) — commits containing secrets are blocked locally and in CI.
`/secret-scan-setup` is a Claude Code command from DisplayNote's `displaynote-engineering` plugin (install it with `/plugin install displaynote-engineering`); it is not part of this repository.

Do not run `utils/setup-hooks.sh` afterwards: it copies `utils/pre-commit.sh` over
`.git/hooks/pre-commit` and would replace the secret-scan hook.

## 2. Prerequisites

- CMake ≥ 3.16 and a C++17 compiler (`CMakeLists.txt`).
- Qt 5.15 or Qt 6 with `Core`, `Network`, `Xml` (and `Test` for tests), with SSL support.
  DisplayNote packages are built with Qt 6.8.8 (`ci/azure-pipelines.yml`); with Qt 6 the build
  also looks for `Qt6Core5Compat`.
- Optional: QCA (`WITH_QCA`, picked up automatically if found), libomemo-c + pkg-config
  (`BUILD_OMEMO`), GStreamer (`WITH_GSTREAMER`), Doxygen (`BUILD_DOCUMENTATION`).
- Debian/Ubuntu and macOS package lists used by upstream CI:
  `tests/travis/install-build-depends-debian`, `tests/travis/install-build-depends-macos`.

## 3. Configure and build

```bash
cmake -B build -DBUILD_TESTS=ON -DBUILD_EXAMPLES=OFF
cmake --build build
```

Add `-DCMAKE_PREFIX_PATH=<Qt install>` (e.g. `~/Qt/6.8.8/macos`) if Qt is not found, and
`-DQT_VERSION_MAJOR=5` or `6` to force a Qt major version. `build/` and `install/` are
git-ignored.

## 4. Run the tests

```bash
cd build && ctest --output-on-failure
```

See [testing.md](testing.md) for internal and integration tests.

## 5. Package build (optional)

To reproduce what DisplayNote CI packages for one platform, follow the `README.md` "Building"
section (Win64 and macOS commands: `cmake --install build --prefix <Platform>/<BuildType>` then
`conan export-pkg`). Background in [release.md](release.md).
