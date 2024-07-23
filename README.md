<!--
SPDX-FileCopyrightText: 2009 Manjeet Dahiya <manjeetdahiya@gmail.com>

SPDX-License-Identifier: CC0-1.0
-->

# QXmpp - Cross-platform C++/Qt XMPP library

<h1 align="center">
<picture>
    <img alt="QXmpp logo" src="./logo.svg" height="150">
</picture>
</h1>
<p align="center">
    <a href="https://xmpp.org/extensions/xep-0459.html">
        <img alt="XMPP:2022 Client IM Mobile+ Compliance Badge" src="https://img.shields.io/badge/XMPP%3A2022%20Client-Core%20IM%20Mobile%2B-green">
    </a>
</p>
<p align="center">
    <a href="https://github.com/qxmpp-project/qxmpp/actions">
        <img alt="Build Status" src="https://github.com/qxmpp-project/qxmpp/workflows/tests/badge.svg">
    </a>
    <a href="https://codecov.io/gh/qxmpp-project/qxmpp">
        <img alt="Code Coverage" src="https://img.shields.io/codecov/c/github/qxmpp-project/qxmpp.svg">
    </a>
    <a href="https://github.com/qxmpp-project/qxmpp/releases/latest">
        <img alt="Latest release" src="https://img.shields.io/github/v/release/qxmpp-project/qxmpp">
    </a>
    <a href="https://doc.qxmpp.org/">
        <img alt="Documentation" src="https://img.shields.io/website?down_message=offline&label=documentation&up_message=online&url=https%3A%2F%2Fdoc.qxmpp.org%2F">
    </a>
    <a href="xmpp:qxmpp@muc.kaidan.im?join">
        <img alt="Development Chat" src="https://search.jabbercat.org/api/1.0/badge?address=qxmpp@muc.kaidan.im">
    </a>
    <a href="https://liberapay.com/QXmpp/donate">
        <img alt="Donate using Liberapay" src="https://img.shields.io/liberapay/patrons/QXmpp.svg?logo=liberapay">
    </a>
    <a href="https://api.reuse.software/info/github.com/qxmpp-project/qxmpp">
        <img alt="REUSE status" src="https://api.reuse.software/badge/github.com/qxmpp-project/qxmpp">
    </a>
</p>

QXmpp is a cross-platform C++ XMPP client and server library. It is written
in C++ and uses the Qt framework.

QXmpp strives to be as easy to use as possible. The underlying TCP socket, the core XMPP RFCs
(RFC6120 and RFC6121) and the [supported XMPP extensions][xeps] have been nicely encapsulated in
classes.
With QXmpp, it is possible to build XMPP clients complying with the
[XMPP Compliance Suites 2022][xmpp-compliance] for IM and Advanced Mobile.
It comes with full API documentation, automatic tests and examples.

QXmpp uses Qt extensively. Thus, users need to have a good knowledge of C++ and Qt basics
(including the concept of signals/slots and Qt's data types).
Qt is the only third party library required to build QXmpp, but libraries such as GStreamer enable
additional features.

QXmpp is released under the terms of the GNU Lesser General Public License, version 2.1 or later.

## Building

**NOTE**: It's mandatory to create a `SHARED LIBRARY` because QXMPP lives under the LGPL License.

### Win64 platform

1. Go to QXmpp root folder

2. Set Win64/Qt6 environment
    ```
    "c:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"
    set Qt6_DIR=C:\Qt\6.5.6\msvc2019_64\lib\cmake\Qt6
    set Qt6Core5Compat_DIR=C:\Qt\6.5.6\msvc2019_64\lib\cmake\Qt6Core5Compat
    ```
3. Create project
    ```
    c:\Qt\Tools\CMake_64\bin\cmake.exe -B build -DBUILD_SHARED=ON -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOCUMENTATION=OFF .
    ```

4. Build and create Release package
    ```
    cmake --build build --config Release
    cmake --install build --prefix install\Windows\Release --config Release
    conan export-pkg . qxmpp/1.6.1@dn/stable -pr msvc19.x86_64.release -f
    ```

5. Build and create Debug package
    ```
    cmake --build build --config Debug
    cmake --install build --prefix install\Windows\Debug --config Debug
    conan export-pkg . qxmpp/1.6.1@dn/stable -pr msvc19.x86_64.debug -f
    ```

### MacOS platform
```
$ git clone  https://github.com/qxmpp-project/qxmpp
$ git checkout v1.6.1
$ cd qxmpp
$ mkdir build
$ cd build
$ cmake -DCMAKE_PREFIX_PATH=~/Qt/6.5.6/macos/ -DBUILD_SHARED=ON -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOCUMENTATION=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES="x86_64" -DCMAKE_INSTALL_PREFIX:PATH=./install ..
$ cmake --build .
$ cmake --build . --target install
$ conan export-pkg .. qxmpp/1.6.1@dn/develop -pr macos.x86_64.release -f
```
To generate Debug package change ```-DCMAKE_BUILD_TYPE=Debug``` and select the profile ```macos.x86_64.debug```


## Building (original)

QXmpp requires **Qt 5.15** or **Qt 6.0 or higher** with SSL enabled.

You can build QXmpp with CMake:
```
mkdir build
cd build
cmake ..
cmake --build .
```

You can pass the following arguments to CMake:

Option | Default | Description
---|---|---
`BUILD_SHARED` | `ON` | Build as shared library, otherwise static
`BUILD_DOCUMENTATION` | `ON` | Build documentation, requires Doxygen
`BUILD_EXAMPLES` | `ON` | Build examples
`BUILD_TESTS` | `ON` | Build unit tests
`BUILD_INTERNAL_TESTS` | `OFF` | Build unit tests testing private parts of the API
`BUILD_OMEMO` | `OFF` | Build the [OMEMO module][omemo]
`WITH_GSTREAMER` | `OFF` | Enable audio/video over Jingle
`QT_VERSION_MAJOR=5/6` | | to build with a specific Qt major version, prefers Qt 6 if undefined

For example, to build without unit tests you could do:
```
cmake .. -DBUILD_TESTS=OFF
```

## Installing

After building QXmpp, you can install it using the following command:
```
cmake --build . --target install
```

## Examples

There are various [examples][examples] in order to quickly start using QXmpp.

### `example_0_connected`

This example connects to the XMPP server and starts receiving presences from the server.
You can see whether the user is online and if the user is in your roster (contact list).

### `example_1_echoClient`

This is a very simple bot which echoes the message sent to it.
The example helps to understand how to receive and send messages.

## Documentation

There is an API documentation for the [latest stable QXmpp version][qxmpp-documentation] and one
for the [master branch][qxmpp-master-documentation].

## Supported Platforms

QXmpp should work on all [platforms supported by Qt][supported-platforms].

## Bugs

If you think you have found a bug in QXmpp, we would like to hear about it.
That way, we can fix it.
Before [reporting a bug][issues], please check if the issue is already known at.

## Contributing

If you are interested in contributing to QXmpp, please have a look at our [contribution guidelines][contributing].

[xeps]: https://doc.qxmpp.org/qxmpp-1/xep.html
[contributing]: /CONTRIBUTING.md
[examples]: /examples
[issues]: https://github.com/qxmpp-project/qxmpp/issues
[omemo]: /src/omemo/README.md
[qxmpp-documentation]: https://doc.qxmpp.org
[qxmpp-master-documentation]: https://doc.qxmpp.org/qxmpp-dev/
[supported-platforms]: https://doc.qt.io/qt-5/supported-platforms.html
[xmpp-compliance]: https://xmpp.org/extensions/xep-0459.html
