from setuptools import setup, Extension
dwm_ext = Extension("dwm_ext",
    sources=["audio_player/platform/windows/dwm_ext.c"],
    libraries=["dwmapi", "ole32", "uuid", "user32", "comctl32"],
    extra_compile_args=["-O2"])
setup(name="dwm_ext", version="1.0", ext_modules=[dwm_ext], packages=[])
