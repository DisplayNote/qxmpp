import os

from conans import ConanFile
from conans import tools
from conans.errors import ConanException


class QxmppConan(ConanFile):
    settings = 'os', 'compiler', 'build_type', 'arch'
    description = 'QXmpp library'
    url = 'None'
    license = 'None'
    generators = 'qmake'

    def _source_folder(self):
        # common/build-unix.yml@ci and windows-x86_64/build.yml@ci stage each
        # build under <Platform>/<BuildType> at the root of the build-folder
        # artifact. macOS goes one level deeper, <Platform>/<arch>/<BuildType>,
        # so the x86_64 and arm64 stages do not overwrite each other in that
        # shared artifact. The arch level carries conan's own settings.arch
        # value ('x86_64', 'armv8'), so it drops in with no translation table.
        if self.settings.os == 'Macos':
            return os.path.join(str(self.settings.os),
                                str(self.settings.arch),
                                str(self.settings.build_type))

        return os.path.join(str(self.settings.os), str(self.settings.build_type))

    def package(self):
        src = self._source_folder()

        # self.copy() from a directory that is not there copies nothing and
        # still succeeds, so a renamed or missing stage folder would publish a
        # silently empty package that only fails at link time on a consumer.
        if not os.path.isdir(os.path.join(self.build_folder, src)):
            raise ConanException("No build output at '{}'".format(src))

        # Keeps the include/ + lib/ (+ bin/ on Windows) layout that the CMake
        # install step produces.
        self.copy('*', src=src)

    def package_info(self):
        self.cpp_info.libdirs = ['lib']
        self.cpp_info.libs = tools.collect_libs(self, 'lib')

        self.cpp_info.includedirs.extend(['include'])
