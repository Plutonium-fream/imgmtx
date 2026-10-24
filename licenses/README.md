# Native-runtime license sources

These unmodified upstream texts supplement the licenses collected from installed dependencies during a Windows release build:

- `Tcl-LICENSE`: [Tcl 8.6.12 license.terms](https://github.com/tcltk/tcl/blob/core-8-6-12/license.terms).
- `OpenSSL-LICENSE`: [OpenSSL 3.5.8 LICENSE.txt](https://github.com/openssl/openssl/blob/openssl-3.5.8/LICENSE.txt), for the runtime's OpenSSL 3.x Apache-2.0 terms.
- `libffi-LICENSE`: [libffi 3.4.4 LICENSE](https://github.com/libffi/libffi/blob/v3.4.4/LICENSE), for the libffi ABI-8 runtime.

The package builder also copies the Python distribution's complete `LICENSE.txt`, Pillow's full wheel license (including bundled codec notices), the installed Tk `license.terms`, and the installed PyInstaller licensing terms/bootloader exception. Copies are included both inside the executable and as readable files in the portable ZIP.

Review the collected runtime and license versions when changing the Python distribution or native libraries used for a release. Upstream copyright notices identify third-party authors; they are not private application-user information and must be retained.
