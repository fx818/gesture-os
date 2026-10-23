// Gesture OS window control.
//
// Why this exists: on GNOME Wayland there is no public API for an ordinary process to move another
// application's window. xdotool and wmctrl are X11-only, and org.gnome.Shell.Eval has been
// disabled outside unsafe mode since GNOME 41. Code running INSIDE gnome-shell can do it, so this
// extension exposes the smallest possible surface over D-Bus and nothing else.
//
// Scope is deliberately tiny. Everything gesture-os can do with ordinary key injection — workspace
// switching, half-tiling, show-desktop — it already does without this extension. The one thing
// only the compositor can provide is arbitrary-rectangle placement, which is what ray-cast tiling
// and Jev point B need.
//
// GNOME 45+ ESM module.

import Gio from 'gi://Gio';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const API_VERSION = 1;
const BUS_NAME = 'org.gestureos.Shell';
const OBJECT_PATH = '/org/gestureos/Shell';

class ShellService {
    constructor(extension) {
        this._extension = extension;
    }

    GetApiVersion() {
        return API_VERSION;
    }

    _describe(win) {
        const frame = win.get_frame_rect();
        return {
            id: win.get_id(),
            title: win.get_title() ?? '',
            wm_class: win.get_wm_class() ?? '',
            pid: win.get_pid(),
            monitor: win.get_monitor(),
            workspace: win.get_workspace()?.index() ?? -1,
            focused: win.has_focus(),
            maximized: win.is_maximized(),
            fullscreen: win.is_fullscreen(),
            rect: { x: frame.x, y: frame.y, width: frame.width, height: frame.height },
        };
    }

    _windows() {
        // NORMAL only: docks, panels and notification popups are not things a user gestures at,
        // and including them would let a stray ray-cast land on the shell itself.
        return global.get_window_actors()
            .map(actor => actor.meta_window)
            .filter(win => win && win.get_window_type() === Meta.WindowType.NORMAL);
    }

    _find(id) {
        return this._windows().find(win => win.get_id() === id) ?? null;
    }

    ListWindows() {
        return JSON.stringify(this._windows().map(win => this._describe(win)));
    }

    GetFocused() {
        const win = this._windows().find(w => w.has_focus());
        return JSON.stringify(win ? this._describe(win) : null);
    }

    GetLayout() {
        const monitors = Main.layoutManager.monitors.map((monitor, index) => ({
            index,
            primary: index === Main.layoutManager.primaryIndex,
            rect: {
                x: monitor.x, y: monitor.y,
                width: monitor.width, height: monitor.height,
            },
            // The work area excludes panels and docks. Placing a window using the full monitor
            // rect puts its titlebar underneath the top bar.
            work_area: (() => {
                const wa = global.workspace_manager
                    .get_active_workspace()
                    .get_work_area_for_monitor(index);
                return { x: wa.x, y: wa.y, width: wa.width, height: wa.height };
            })(),
        }));
        return JSON.stringify({
            monitors,
            workspaces: global.workspace_manager.get_n_workspaces(),
            active_workspace: global.workspace_manager.get_active_workspace_index(),
            windows: this._windows().map(win => this._describe(win)),
        });
    }

    MoveWindowTo(id, x, y, width, height) {
        const win = this._find(id);
        if (!win)
            return false;
        // A maximized or tiled window ignores move_resize_frame; unmaximize first or the call
        // silently does nothing, which is the most confusing possible failure.
        //
        // Mutter 50 API: `get_maximized()` is gone (use `is_maximized()`), and `unmaximize()`
        // now takes no arguments. Verified by introspecting Meta-18.typelib — the first version
        // of this threw "win.get_maximized is not a function" the moment a window existed.
        if (win.is_maximized())
            win.unmaximize();
        win.move_resize_frame(true, x, y, width, height);
        return true;
    }

    SendToMonitor(id, monitor) {
        const win = this._find(id);
        if (!win || monitor < 0 || monitor >= Main.layoutManager.monitors.length)
            return false;
        win.move_to_monitor(monitor);
        return true;
    }

    SendToWorkspace(id, index) {
        const win = this._find(id);
        if (!win || index < 0 || index >= global.workspace_manager.get_n_workspaces())
            return false;
        win.change_workspace_by_index(index, false);
        return true;
    }
}

export default class GestureOsExtension extends Extension {
    enable() {
        try {
            this._export();
        } catch (e) {
            // Log loudly rather than failing silently: a thrown enable() leaves the extension
            // marked ERROR with no indication of why, and the D-Bus name simply never appears.
            console.error(`gesture-os: enable failed: ${e}\n${e.stack ?? ''}`);
            throw e;
        }
    }

    _export() {
        this._service = new ShellService(this);
        const iface = this.dir.get_child('dbus.xml');
        const [, contents] = iface.load_contents(null);
        const xml = new TextDecoder().decode(contents);

        this._dbus = Gio.DBusExportedObject.wrapJSObject(xml, this._service);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._ownerId = Gio.bus_own_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE, null, null, null,
        );
        console.log(`gesture-os: exported ${BUS_NAME} v${API_VERSION}`);
    }

    disable() {
        // Unexport on disable, not just on uninstall: GNOME disables extensions when the screen
        // locks, and a stale D-Bus name would leave the client talking to nothing.
        if (this._ownerId) {
            Gio.bus_unown_name(this._ownerId);
            this._ownerId = null;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        this._service = null;
    }
}
