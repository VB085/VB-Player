from setuptools import setup, Extension
setup(name="asio_ext", version="1.0",
    ext_modules=[Extension("asio_ext",
        sources=["audio_player/platform/windows/asio_ext.c"],
        libraries=["ole32", "uuid", "oleaut32"],
        extra_compile_args=["-O2"])], packages=[])
