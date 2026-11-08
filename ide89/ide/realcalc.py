"""
Envoi d'un programme vers une vraie TI-89 Titanium par le câble USB direct.

Sous WSL, la prise USB de Windows est partagée avec Linux par usbipd-win :
  - une seule fois, en PowerShell administrateur :  usbipd bind --hardware-id 0451:e004
  - à chaque branchement, l'IDE fait :               usbipd attach --wsl --hardware-id 0451:e004
Puis l'envoi passe par les bibliothèques TI (libticalcs2/libticables2) via ctypes.
"""
import ctypes
import glob
import os
import re
import subprocess
import time

USBIPD = "/mnt/c/Program Files/usbipd-win/usbipd.exe"
TI_VID, TI89T_PID = "0451", "e004"
HWID = f"{TI_VID}:{TI89T_PID}"

# Constantes de tilibs (ticables.h, ticonv.h, ticalcs.h)
CABLE_USB = 5            # câble USB direct (DirectLink)
PORT_1 = 1
CALC_TI89T_USB = 14
MODE_NORMAL = 0


class SendError(Exception):
    pass


# ------------------------------------------------------------------ usbipd (Windows)
def usbipd_state():
    """Retourne (busid, état) de la TI-89 Titanium vue par Windows, ou (None, message)."""
    if not os.path.exists(USBIPD):
        return None, "usbipd-win is not installed on Windows"
    try:
        out = subprocess.run([USBIPD, "list"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"usbipd does not respond ({e})"
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(.*?)\s{2,}(\S.*)$", line)
        if m and m.group(2).lower() == HWID:
            return m.group(1), m.group(4).strip()
    return None, "calculator not detected by Windows (is it plugged in and turned on?)"


def usbipd_attach():
    """Rattache la calculatrice à WSL. Retourne un message d'erreur, ou None si c'est fait."""
    try:
        p = subprocess.run([USBIPD, "attach", "--wsl", "--hardware-id", HWID],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"usbipd attach failed ({e})"
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip()
        if "not shared" in msg.lower() or "bind" in msg.lower():
            return ("the calculator is not shared with WSL yet. Once, in an "
                    f"administrator PowerShell:  usbipd bind --hardware-id {HWID}")
        return msg or f"usbipd attach failed (exit code {p.returncode})"
    return None


# ------------------------------------------------------------------ côté Linux
def wsl_device():
    """Chemin /dev/bus/usb/... de la calculatrice si elle est visible dans WSL, sinon None."""
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            with open(os.path.join(d, "idVendor")) as f:
                vid = f.read().strip()
            with open(os.path.join(d, "idProduct")) as f:
                pid = f.read().strip()
            if vid == TI_VID and pid == TI89T_PID:
                with open(os.path.join(d, "busnum")) as f:
                    bus = int(f.read())
                with open(os.path.join(d, "devnum")) as f:
                    dev = int(f.read())
                return f"/dev/bus/usb/{bus:03d}/{dev:03d}"
        except OSError:
            continue
    return None


UDEV_RULE = ('SUBSYSTEM=="usb", ATTR{idVendor}=="0451", ATTR{idProduct}=="e004", '
             'MODE="0666"')
UDEV_FILE = "/etc/udev/rules.d/70-ti89titanium.rules"


def udev_rule_installed():
    return os.path.exists(UDEV_FILE)


def udev_install_command():
    return (f"echo '{UDEV_RULE}' | sudo tee {UDEV_FILE} && "
            "sudo udevadm control --reload-rules && sudo udevadm trigger")


# ------------------------------------------------------------------ tilibs
_libs = None


def _load():
    global _libs
    if _libs:
        return _libs
    tifiles = ctypes.CDLL("libtifiles2.so.11")
    ticables = ctypes.CDLL("libticables2.so.8")
    ticalcs = ctypes.CDLL("libticalcs2.so.13")
    ticables.ticables_handle_new.restype = ctypes.c_void_p
    ticables.ticables_handle_new.argtypes = [ctypes.c_int, ctypes.c_int]
    ticables.ticables_handle_del.argtypes = [ctypes.c_void_p]
    ticables.ticables_options_set_timeout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    ticables.ticables_error_get.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    ticalcs.ticalcs_handle_new.restype = ctypes.c_void_p
    ticalcs.ticalcs_handle_new.argtypes = [ctypes.c_int]
    ticalcs.ticalcs_handle_del.argtypes = [ctypes.c_void_p]
    ticalcs.ticalcs_cable_attach.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    ticalcs.ticalcs_cable_detach.argtypes = [ctypes.c_void_p]
    ticalcs.ticalcs_calc_isready.argtypes = [ctypes.c_void_p]
    ticalcs.ticalcs_calc_send_var2.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
    ticalcs.ticalcs_error_get.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    tifiles.tifiles_library_init()
    ticables.ticables_library_init()
    ticalcs.ticalcs_library_init()
    _libs = (tifiles, ticables, ticalcs)
    return _libs


def _error_text(err):
    _, ticables, ticalcs = _load()
    for fn in (ticalcs.ticalcs_error_get, ticables.ticables_error_get):
        msg = ctypes.c_void_p()
        if fn(err, ctypes.byref(msg)) == 0 and msg.value:
            return ctypes.string_at(msg.value).decode("utf-8", "replace").strip()
    return f"error {err}"


def send_file(path):
    """Envoie un fichier .89z/.89p... à la TI-89 Titanium. Lève SendError en cas d'échec."""
    _, ticables, ticalcs = _load()
    cable = ticables.ticables_handle_new(CABLE_USB, PORT_1)
    if not cable:
        raise SendError("cannot create the USB cable handle")
    calc = ticalcs.ticalcs_handle_new(CALC_TI89T_USB)
    attached = False
    try:
        ticables.ticables_options_set_timeout(cable, 30)       # 3 s (en dixièmes)
        err = ticalcs.ticalcs_cable_attach(calc, cable)
        if err:
            raise SendError("cable: " + _error_text(err))
        attached = True
        err = ticalcs.ticalcs_calc_isready(calc)
        if err:
            raise SendError("the calculator does not respond: " + _error_text(err))
        err = ticalcs.ticalcs_calc_send_var2(calc, MODE_NORMAL, os.path.abspath(path).encode())
        if err:
            raise SendError("transfer: " + _error_text(err))
    finally:
        if attached:
            ticalcs.ticalcs_cable_detach(calc)
        ticalcs.ticalcs_handle_del(calc)
        ticables.ticables_handle_del(cable)


def send_to_calculator(path, progress=lambda msg: None):
    """Fait tout : vérifie usbipd, rattache à WSL si besoin, puis envoie."""
    dev = wsl_device()
    if dev is None:
        busid, state = usbipd_state()
        if busid is None:
            raise SendError(state)
        progress(f"Sharing USB port {busid} with WSL…")
        err = usbipd_attach()
        if err:
            raise SendError(err)
        for _ in range(50):
            dev = wsl_device()
            if dev:
                break
            time.sleep(0.1)
        if dev is None:
            raise SendError("the calculator does not show up in WSL after sharing")
    if not os.access(dev, os.R_OK | os.W_OK):
        raise SendError("no permission on the USB device. Once, in the terminal:\n  "
                        + udev_install_command() + "\nthen unplug and plug the calculator back in.")
    progress("Sending to the TI-89 Titanium…")
    send_file(path)
