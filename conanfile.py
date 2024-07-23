import os
from conans import ConanFile
from conans import tools

class QxmppConan(ConanFile):
    settings = 'os', 'compiler', 'build_type', 'arch'
    description = '<Description of Qxmpp here>'
    url = 'None'
    license = 'None'
    generators = 'qmake'

    def package(self):
        self.copy('*', 'include', os.path.join('install', str(self.settings.os), str(self.settings.build_type), 'include'))
        self.copy('*.lib', 'lib', os.path.join('install', str(self.settings.os), str(self.settings.build_type), 'lib'))
        self.copy('*.dll', 'bin', os.path.join('install', str(self.settings.os), str(self.settings.build_type), 'bin'))

    def package_info(self):
        self.cpp_info.libs = tools.collect_libs(self)
