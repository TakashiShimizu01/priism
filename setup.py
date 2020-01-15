import glob
import os
import shlex
import subprocess

from distutils.command.build_ext import build_ext
from distutils.command.build_clib import build_clib
from distutils.command.config import config
from distutils.command.install_lib import install_lib
from setuptools import setup, find_packages, Command

def _get_version():
    cwd = os.path.dirname(__file__)
    cwd = cwd if len(cwd) > 0 else '.'
    version_file = os.path.join(cwd, 'python/priism/core/version.py')
    with open(version_file, 'r') as f:
        lines = f.readlines()
    version_line = filter(lambda x: x.startswith('__version__'), lines)
    try:
        version = next(version_line).strip('\n').split('=')[1].strip(" '")
    except StopIteration:
        version = '0.0.0'
    return version

version = _get_version()
print('PRIISM Version = {}'.format(version))

def check_command_availability(cmd):
    if isinstance(cmd, list):
        return [check_command_availability(_cmd) for _cmd in cmd]
    else:
        assert isinstance(cmd, str)
        return subprocess.call(['which', cmd], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL) == 0


def execute_command(cmdstring, cwd=None):
    retcode = subprocess.call(shlex.split(cmdstring), cwd=cwd)
    if retcode != 0:
        print('WARNING: command "{}" failed to execute'.format(cmdstring))
    return retcode


class priism_build_ext(build_ext):
    user_options = [('eigen3-include-dir=', 'E', 'specify directory for Eigen3'),
                    ('openblas-library-dir=', 'B', 'specify directory for OpenBLAS')]

    def initialize_options(self):
        super(priism_build_ext, self).initialize_options()
        self.eigen3_include_dir = None
        self.fftw3_root_dir = None
        self.openblas_library_dir = None
        self.priism_build_dir = 'build_ext'

    def finalize_options(self):
        super(priism_build_ext, self).finalize_options()
        print('eigen3-include-dir={}'.format(self.eigen3_include_dir))
        print('fftw3-root-dir={}'.format(self.fftw3_root_dir))
        print('openblas-library-dir={}'.format(self.openblas_library_dir))

    def run(self):
        super(priism_build_ext, self).run()
        for cmd in self.get_sub_commands():
            self.run_command(cmd)

        if not os.path.exists(self.build_lib):
            self.run_command('build')

        self.build_sakura()
        self.build_smili()
    
    def build_sakura(self):
        subdirs = ['bin', 'python-binding']
        libs = ['libsakura.so', 'libsakurapy.so']
        libsakura_dir = '{}/libsakura'.format(self.priism_build_dir)
        dst_dir = os.path.join(self.build_lib, 'priism/external/sakura')
        assert os.path.exists(dst_dir)
        for d, f in zip(subdirs, libs):
            src = os.path.join(libsakura_dir, d, f)
            assert os.path.exists(src)
            dst = os.path.join(dst_dir, f)
            self.copy_file(src, dst)

    def build_smili(self):
        smili_dir = 'sparseimaging/c'
        smili_libs = ['libmfista_{}.so'.format(suffix) for suffix in ('fft', 'nufft')]
        for s in smili_libs:
            src = os.path.join(smili_dir, s)
            assert os.path.exists(src)
            dst_dir = os.path.join(self.build_lib, 'priism/core')
            assert os.path.exists(dst_dir)
            dst = os.path.join(dst_dir, s)
            self.copy_file(src, dst)

    sub_commands = build_ext.sub_commands + [('configure_ext', None)]   


class download_smili(config):
    user_options = []

    def initialize_options(self):
        super(download_smili, self).initialize_options()

        is_git_ok, is_curl_ok, is_wget_ok = check_command_availability(['git', 'curl', 'wget'])
        package = 'sparseimaging'
        branch = 'smili'
        zipname = '{}.zip'.format(branch)
        base_url = 'https://github.com/ikeda46/{}'.format(package)
        if is_git_ok:
            url = base_url + '.git'
            self.download_cmd = 'git clone {}'.format(url)
        elif is_curl_ok:
            url = base_url + '/archive/{}'.format(zipname)
            self.download_cmd = 'curl -L -O {}'.format(url)
        elif is_wget_ok:
            url = base_url + '/archive/{}'.format(zipname)
            self.download_cmd = 'wget {}'.format(url)
        else:
            raise FileNotFoundError('No download command found: you have to install git or curl or wget')

        if is_git_ok:
            self.epilogue_cmds = ['git checkout {}'.format(branch)]
            self.epilogue_cwd = package
        else:
            self.epilogue_cmds = ['unzip {}'.format(zipname),
                                  'ln -s {0}-{1} {0}'.format(package, branch)]
            self.epilogue_cwd = '.'
        self.package_directory = package

    def finalize_options(self):
        super(download_smili, self).finalize_options()

    def run(self):
        super(download_smili, self).run()

        if not os.path.exists(self.package_directory):
            execute_command(self.download_cmd)
            for cmd in self.epilogue_cmds:
                execute_command(cmd, cwd=self.epilogue_cwd)


class download_sakura(config):
    user_options = []

    def initialize_options(self):
        super(download_sakura, self).initialize_options()

        is_curl_ok, is_wget_ok = check_command_availability(['curl', 'wget'])
        package = 'libsakura'
        version = '5.0.7'
        tgzname = '{}-{}.tgz'.format(package, version)
        url = 'https://alma-intweb.mtk.nao.ac.jp/~nakazato/libsakura/{}'.format(tgzname)
        if is_curl_ok:
            self.download_cmd = 'curl -L -O {}'.format(url)
        elif is_wget_ok:
            self.download_cmd = 'wget {}'.format(url)
        else:
            raise FileNotFoundError('No download command found: you have to install curl or wget')

        self.epilogue_cmds = ['tar zxvf {}'.format(tgzname)]
        self.epilogut_cwd = '.'
        self.package_directory = package
        self.working_directory = self.package_directory

    def finalize_options(self):
        super(download_sakura, self).finalize_options()

    def run(self):
        super(download_sakura, self).run()

        if not os.path.exists(self.package_directory):
            execute_command(self.download_cmd)
            for cmd in self.epilogue_cmds:
                execute_command(cmd, cwd=self.epilogut_cwd)


class configure_ext(Command):
    user_options = [('eigen3-include-dir=', 'E', 'specify directory for Eigen3'),
                    ('openblas-library-dir=', 'B', 'specify directory for OpenBLAS')]

    def initialize_options(self):
        is_cmake_ok = check_command_availability('cmake')
        if not is_cmake_ok:
            raise FileNotFoundError('Command "cmake" is not found. Please install.')
        self.eigen3_include_dir = None
        self.fftw3_root_dir = None
        self.openblas_library_dir = None
        self.priism_build_dir = None

    def finalize_options(self):
        self.set_undefined_options(
            'build_ext',
            ('eigen3_include_dir', 'eigen3_include_dir'),
            ('openblas_library_dir', 'openblas_library_dir'),
            ('priism_build_dir', 'priism_build_dir')
        )
        print('eigen3-include-dir={}'.format(self.eigen3_include_dir))
        print('fftw3-root-dir={}'.format(self.fftw3_root_dir))
        print('openblas-library-dir={}'.format(self.openblas_library_dir))
    
    def __configure_cmake_command(self):
        cmd = 'cmake .. -DCMAKE_INSTALL_PREFIX=./installed'
        
        if self.eigen3_include_dir is not None:
            cmd += ' -DEIGEN3_INCLUDE_DIR={}'.format(self.eigen3_include_dir)

        if self.openblas_library_dir is not None:
            cmd += ' -DOPENBLAS_LIBRARY_DIR={}'.format(self.openblas_library_dir)
            
        return cmd

    def run(self):
        # download external packages
        for cmd in self.get_sub_commands():
            self.run_command(cmd)

        # configure with cmake
        if not os.path.exists(self.priism_build_dir):
            os.mkdir(self.priism_build_dir)

        cache_file = os.path.join(self.priism_build_dir, 'CMakeCache.txt')
        if os.path.exists(cache_file):
            os.remove(cache_file)

        cmd = self.__configure_cmake_command()
        execute_command(cmd, cwd=self.priism_build_dir)

    sub_commands = build_ext.sub_commands + [('download_sakura', None), ('download_smili', None)]


class priism_install_lib(install_lib):
    def initialize_options(self):
        super(priism_install_lib, self).initialize_options()
        self.priism_build_dir = None

    def finalize_options(self):
        super(priism_install_lib, self).finalize_options()
        self.set_undefined_options(
            'build_ext',
            ('priism_build_dir', 'priism_build_dir')
        )
        print('priism_build_dir = {}'.format(self.priism_build_dir))
        print('install_lib = {}'.format(self.install_dir))
        print('build_dir = {}'.format(self.build_dir))

    def run(self):
        super(priism_install_lib, self).run()
        #self.install_sakura()
        #self.install_smili()

    def build_sakura(self):
        subdirs = ['bin', 'python-binding']
        libs = ['libsakura.so', 'libsakurapy.so']
        libsakura_dir = '{}/libsakura'.format(self.priism_build_dir)
        subtree = 'priism/external/sakura'
        src_dir = os.path.join(self.build_dir, subtree)
        dst_dir = os.path.join(self.install_dir, subtree)
        assert os.path.exists(dst_dir)
        for d, f in zip(subdirs, libs):
            src = os.path.join(libsakura_dir, d, f)
            assert os.path.exists(src)
            dst = os.path.join(dst_dir, f)
            self.copy_file(src, dst)

    def build_smili(self):
        smili_dir = 'sparseimaging/c'
        smili_libs = ['libmfista_{}.so'.format(suffix) for suffix in ('fft', 'nufft')]
        for s in smili_libs:
            src = os.path.join(smili_dir, s)
            assert os.path.exists(src)
            dst_dir = os.path.join(self.build_lib, 'priism/core')
            assert os.path.exists(dst_dir)
            dst = os.path.join(dst_dir, s)
            self.copy_file(src, dst)
        

setup(
    name='priism',
    version=version,
    packages=find_packages('python', exclude=['priism.test']),
    package_dir={'':'python'},
    install_requires=['numpy'],
    cmdclass={
        'build_ext': priism_build_ext,
        'download_sakura': download_sakura,
        'download_smili': download_smili,
        'configure_ext': configure_ext,
        #'install_lib': priism_install_lib
    }
)