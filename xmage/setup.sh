#!/bin/sh

HOST_DOMAIN=xmage.home.demongeot.biz
XMAGE_DOMAIN=xmage.today
XMAGE_WEBSITE="http://$XMAGE_DOMAIN"
XMAGE_ROOT_DIR=/opt/xmage
XMAGE_HOME_DIR=/opt/xmage
XMAGE_HOME_CONFIG_DIR=/opt/xmage/.config
XMAGE_APPS_DIR="$XMAGE_ROOT_DIR/apps"
XMAGE_CURRENT_VERSION_PATH="$XMAGE_APPS_DIR/current"
XMAGE_SERVER_START_SCRIPT="$XMAGE_ROOT_DIR/start_server.sh"
XMAGE_SERVER_CONFIG_PATH="$XMAGE_CURRENT_VERSION_PATH/xmage/mage-server/config/config.xml"
XMAGE_SERVER_LEASE_PERIOD=50000
XMAGE_SERVER_THREADS=2
XMAGE_SYSTEMD_CONFIG_HOME="$XMAGE_HOME_CONFIG_DIR/systemd/user"
XMAGE_SYSTEMD_UNIT_DIR="$XMAGE_SYSTEMD_CONFIG_HOME"
XMAGE_SYSTEMD_UNIT_FILENAME=xmage.service
XMAGE_SYSTEMD_UNIT_TIMER_FILENAME=xmage.timer
XMAGE_SYSTEMD_UNIT_PATH="$XMAGE_SYSTEMD_UNIT_DIR/$XMAGE_SYSTEMD_UNIT_FILENAME"
XMAGE_SYSTEMD_UNIT_TIMER_PATH="$XMAGE_SYSTEMD_UNIT_DIR/$XMAGE_SYSTEMD_UNIT_TIMER_FILENAME"

set -e

if [ "$1" = '-h' ] || [ "$1" = '--help' ]; then
	echo "USAGE: $(basename "$0") [--restart-anyway]"
	exit 0
fi

need_restart=false
if [ "$1" = '--restart-anyway' ]; then
	need_restart=true
fi

if ! id xmage >/dev/null 2>&1; then
	echo "Error: xmage system user doesn't exist" >&2
	echo "Please create it with the following command:" >&2
	echo "\$ sudo adduser --system --group --home '$XMAGE_HOME_DIR' xmage" >&2
	exit 4
fi

if [ ! -e "/var/lib/systemd/linger/xmage" ]; then
	echo "Error: lingering is not enabled for xmage user" >&2
	echo "Please enable it with the following command:" >&2
	echo "\$ sudo loginctl enable-linger xmage" >&2
	exit 4
fi

_log() {
	if [ "$LOG_MODE" = 'datetime' ]; then
		echo "$(date '+%Y-%m-%d %H:%M:%S')  $1"
	elif [ "$LOG_MODE" != 'null' ]; then
		echo "$1"
	fi
}

_log "Downloading web page of $XMAGE_DOMAIN ..."
dl_webpage_path="/tmp/webpage-from--$XMAGE_DOMAIN.html"
wget -q -O "$dl_webpage_path" "$XMAGE_WEBSITE"
_log "Downloaded to: $dl_webpage_path"

_log "Searching for the app archive URL in the web page ..."
xmage_archive_url_rel="$(grep '<a [^>]* href="files/mage-full_[^">]\+.zip">Download full BETA client</a>' "$dl_webpage_path" | sed 's#^.*href="\(files/mage-full_[^">]\+.zip\)".*$#\1#g')"
if [ "$xmage_archive_url_rel" = '' ]; then
	echo "Error: failed to find xmage archive URL in downloaded web page '$dl_webpage_path'" >&2
	exit 2
fi
_log "Found: '$xmage_archive_url_rel'"
xmage_archive_url="$XMAGE_WEBSITE/$xmage_archive_url_rel"
_log "Archive URL: '$xmage_archive_url'"

_log "Defining xmage archive filename ..."
xmage_archive_filename="$(basename "$xmage_archive_url_rel")"
_log "Archive filename: '$xmage_archive_filename'"

if ! echo "$xmage_archive_filename" | grep -q '^mage-full_\([^_]\+\)_[0-9-]\{10\}_[0-9-]\{5\}\.zip$'; then
	echo "Error: the archive filename '$xmage_archive_filename' has incorrect format" >&2
	exit 3
fi

_log "Defining xmage latest version ..."
xmage_latest_version="$(echo "$xmage_archive_filename" | sed 's/^mage-full_\([^ ]\+\)\.zip$/\1/g')"
xmage_latest_version_major="$(echo "$xmage_latest_version" | sed 's/^\([^_]\+\)_[0-9-]\{10\}_[0-9-]\{5\}$/\1/g')"
xmage_latest_version_date="$(echo "$xmage_latest_version" | sed 's/^[^_]\+_\([0-9-]\{10\}_[0-9-]\{5\}\)$/\1/g;s/_//g')"
_log "Latest version: $xmage_latest_version_major  $xmage_latest_version_date  ($xmage_latest_version)"

if [ -L "$XMAGE_CURRENT_VERSION_PATH" ]; then
	_log "Defining current installed version ..."
	xmage_installed_version=none
	xmage_installed_version_path="$(realpath "$XMAGE_CURRENT_VERSION_PATH")"
	if [ -d "$xmage_installed_version_path" ]; then
		xmage_installed_version_filename="$(basename "$xmage_installed_version_path")"
		xmage_installed_version="$(echo "$xmage_installed_version_filename" | sed 's/^mage-full_\([^ ]\+\)$/\1/g')"

		if ! echo "$xmage_installed_version" | grep -q '^[^_]\+_[0-9-]\{10\}_[0-9-]\{5\}$'; then
			_log "Installed version: unknown  unknown  ($xmage_installed_version)"
			echo "Warning: the installed version filename '$xmage_installed_version' has incorrect format" >&2
		else
			xmage_installed_version_major="$(echo "$xmage_installed_version" | sed 's/^\([^_]\+\)_[0-9-]\{10\}_[0-9-]\{5\}$/\1/g')"
			xmage_installed_version_date="$(echo "$xmage_installed_version" | sed 's/^[^_]\+_\([0-9-]\{10\}_[0-9-]\{5\}\)$/\1/g;s/_//g')"
			_log "Installed version: $xmage_installed_version_major  $xmage_installed_version_date  ($xmage_installed_version)"
		fi
	fi

	_log "Analysing if version differs ..."
	if [ "$xmage_installed_version" != "$xmage_latest_version" ]; then
		_log "Versions differs: will installed the latest one"
	else
		_log "Latest version is already installed and current: installing nothing"
		install_nothing=true
	fi
fi

if [ "$install_nothing" != 'true' ]; then

	xmage_archive_dest="/tmp/$xmage_archive_filename"
	if [ -f "$xmage_archive_dest" ]; then
		_log "Using already downloaded archive '$xmage_archive_dest'"
	else
		_log "Downloading xmage archive ..."
		wget -q -O "$xmage_archive_dest" "$xmage_archive_url"
	fi

	xmage_archive_dir="$(basename "$xmage_archive_filename" '.zip')"
        xmage_latest_version_dest_dir="$XMAGE_APPS_DIR/$xmage_archive_dir"
	_log "Extracting xmage archive to '$xmage_latest_version_dest_dir' ..."
	[ -d "$XMAGE_APPS_DIR" ] || mkdir "$XMAGE_APPS_DIR"
	unzip -q -d "$xmage_latest_version_dest_dir" "$xmage_archive_dest" || true

	_log "Creating/updating current version symlink ..."
	rm -f "$XMAGE_CURRENT_VERSION_PATH"
	ln -s "$xmage_archive_dir" "$XMAGE_CURRENT_VERSION_PATH"

	_log "Updating xmage server configuration '$XMAGE_SERVER_CONFIG_PATH' ..."
	sed 's/serverAddress="0\.0\.0\.0"/serverAddress="'"$HOST_DOMAIN"'"/g' -i "$XMAGE_SERVER_CONFIG_PATH"
	sed 's/serverName="mage-server"/serverName="'"$HOST_DOMAIN"'"/g' -i "$XMAGE_SERVER_CONFIG_PATH"
	sed 's/secondaryBindPort="-1"/secondaryBindPort="17172"/g' -i "$XMAGE_SERVER_CONFIG_PATH"
	sed 's/leasePeriod="5000"/leasePeriod="'"$XMAGE_SERVER_LEASE_PERIOD"'"/g' -i "$XMAGE_SERVER_CONFIG_PATH"
	sed 's/numAcceptThreads="2"/numAcceptThreads="'"$XMAGE_SERVER_THREADS"'"/g' -i "$XMAGE_SERVER_CONFIG_PATH"

	need_restart=true
fi


if [ ! -f "$XMAGE_SERVER_START_SCRIPT" ]; then
	_log "Installing xmage server start script ..."
	cat >"$XMAGE_SERVER_START_SCRIPT" <<ENDCAT
#!/bin/sh

set -e

cd "\$(dirname "\$0")/apps/current/xmage/mage-server"

LC_ALL=C
export LC_ALL

#PATH="\$(realpath '../../java/jre1.8.0_381/bin'):\$PATH"
command -v java 2>&1
#export PATH
java -version 2>&1

java -Xms512M -Xmx1024M -Dfile.encoding=UTF-8 -Djava.security.policy=./config/security.policy -Dlog4j.configuration=file:./config/log4j.properties -jar ./lib/mage-server-1.4.50.jar
ENDCAT
	chmod +x "$XMAGE_SERVER_START_SCRIPT"
fi

XDG_RUNTIME_DIR="/run/user/$(id -u xmage)"
export XDG_RUNTIME_DIR
XDG_CONFIG_HOME="$XMAGE_SYSTEMD_CONFIG_HOME"
export XDG_CONFIG_HOME

installed_systemd_files=false
[ -d "$XMAGE_SYSTEMD_UNIT_DIR" ] || mkdir -p "$XMAGE_SYSTEMD_UNIT_DIR"
if [ ! -f "$XMAGE_SYSTEMD_UNIT_PATH" ]; then
	_log "Installing xmage systemd unit '$XMAGE_SYSTEMD_UNIT_PATH' ..."
	cat >"$XMAGE_SYSTEMD_UNIT_PATH" <<ENDCAT
[Unit]
Description=XMage server

[Service]
ExecStart=$XMAGE_SERVER_START_SCRIPT
Restart=on-failure
RestartSec=42s

[Install]
WantedBy=default.target
ENDCAT
	installed_systemd_files=true
fi
if [ ! -f "$XMAGE_SYSTEMD_UNIT_TIMER_PATH" ]; then
	_log "Installing xmage systemd unit timer '$XMAGE_SYSTEMD_UNIT_TIMER_PATH' ..."
	cat >"$XMAGE_SYSTEMD_UNIT_TIMER_PATH" <<ENDCAT
[Unit]
Description=Run XMage server on boot

[Timer]
OnBootSec=1sec

[Install]
WantedBy=timers.target
ENDCAT
	installed_systemd_files=true
fi
if [ "$installed_systemd_files" = 'true' ]; then
	_log "Reloading systemd daemon ..."
	systemctl --user daemon-reload

	_log "Enabling systemd unit ..."
	systemctl --user enable "$XMAGE_SYSTEMD_UNIT_FILENAME"

	_log "Enabling systemd unit timer ..."
	systemctl --user enable "$XMAGE_SYSTEMD_UNIT_TIMER_FILENAME"

	need_restart=true
fi

if [ "$need_restart" = 'true' ]; then
	_log "Stopping server ..."
	systemctl --user stop "$XMAGE_SYSTEMD_UNIT_FILENAME" || true

	_log "Detecting a server running ..."
	server_pid="$(ps aux| (grep 'java .*-jar \./lib/mage-server-[^ ]\+\.jar' || true) | awk '{print $2}')"
	if [ "$server_pid" != '' ]; then
		_log "Server is running with PID: '$server_pid'"
		_log "Stopping currently running server ..."
		kill "$server_pid"
		if [ "$(ps -p "$server_pid" || true)" != '' ]; then
			echo "Warning failed to kill running server with PID '$server_pid'" >&2
			exit 4
		fi
	else
		_log "No server running"
	fi

	_log "Starting the server ..."
	systemctl --user start "$XMAGE_SYSTEMD_UNIT_FILENAME"
else
	_log "Not restarting the server"
fi
