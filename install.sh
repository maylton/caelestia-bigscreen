#!/bin/sh
# Installs Caelestia Big Screen for the current user (no root needed).
#   ./install.sh             command in ~/.local/bin, app menu entry and translations
#   ./install.sh --hyprland  also starts with Hyprland, blurs the quick menu and binds SUPER+G
#   ./install.sh --session   also adds "Caelestia Big Screen (TV mode)" to the login screen (uses sudo)
set -e
here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin/caelestia-bigscreen"
apps="$HOME/.local/share/applications"

missing=""
for module in "Gtk:4.0" "Adw:1" "Gtk4LayerShell:1.0"; do
    python3 -c "import gi; gi.require_version('${module%%:*}', '${module#*:}')" 2>/dev/null || missing="$missing ${module%%:*}"
done
python3 -c "import evdev" 2>/dev/null || missing="$missing python-evdev"
if [ -n "$missing" ]; then
    echo "Missing:$missing"
    echo "Arch Linux: sudo pacman -S gtk4 libadwaita gtk4-layer-shell python-gobject python-evdev"
    exit 1
fi

for po in "$here"/po/*.po; do
    lang=$(basename "$po" .po)
    mkdir -p "$here/locale/$lang/LC_MESSAGES"
    msgfmt -o "$here/locale/$lang/LC_MESSAGES/caelestia-bigscreen.mo" "$po"
done

mkdir -p "$(dirname "$bin")" "$apps"
ln -sf "$here/bin/caelestia-bigscreen" "$bin"
sed "s|@BIN@|$bin|" "$here/data/io.github.maylton.CaelestiaBigScreen.desktop.in" \
    > "$apps/io.github.maylton.CaelestiaBigScreen.desktop"
echo "Installed: $bin"

case "$1" in
--hyprland)
    conf="$HOME/.config/caelestia/hypr-user.lua"
    [ -f "$conf" ] || conf="$HOME/.config/hypr/hyprland.lua"
    if grep -q "caelestia-bigscreen" "$conf" 2>/dev/null; then
        echo "Hyprland already configured in $conf"
    else
        cat >> "$conf" <<LUA

-- Caelestia Big Screen: the gamepad PS/Xbox button shows and hides it
hl.on("hyprland.start", function()
    hl.exec_cmd("$bin --daemon")
end)
hl.layer_rule({ match = { namespace = "^caelestia-bigscreen\$" }, blur = true, ignore_alpha = 0.01, animation = "fade" })
hl.bind("SUPER + G", hl.dsp.exec_cmd("$bin --toggle"))
LUA
        echo "Hyprland configured in $conf (reload with: hyprctl reload)"
    fi
    ;;
--session)
    config="$HOME/.config/caelestia-bigscreen/hyprland-session.lua"
    layout=$(hyprctl getoption input:kb_layout 2>/dev/null | sed -n 's/^str: //p')
    mkdir -p "$(dirname "$config")"
    if [ -f "$config" ]; then
        echo "Kept: $config (already exists)"
    else
        sed "s|@KB_LAYOUT@|${layout:-us}|" "$here/data/hyprland-session.lua.in" > "$config"
        echo "Session config: $config"
    fi
    Hyprland --verify-config -c "$config" 2>&1 | tail -1
    echo "Adding the session to the login screen (needs sudo)…"
    sudo install -Dm755 "$here/data/caelestia-bigscreen-session" /usr/local/bin/caelestia-bigscreen-session
    sudo install -Dm644 "$here/data/caelestia-bigscreen-session.desktop" \
        /usr/local/share/wayland-sessions/caelestia-bigscreen.desktop
    sudo install -Dm644 "$here/data/hyprland-session.lua.in" \
        /usr/local/share/caelestia-bigscreen/hyprland-session.lua.in
    echo "Done: pick \"Caelestia Big Screen (TV mode)\" on the login screen."
    ;;
esac
