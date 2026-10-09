import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar widget for the bundled `machines` command (bin/machines). That command
// decides what counts as a problem and reports each machine's status, issues
// and display text in --json; this widget only shows it.
//
// left = popup · middle = refresh now · right = full table in a terminal.
// Clicking a machine in the popup opens an ssh session to it.
Panel {
  id: root
  moduleName: "io.github.frestina.machines"
  ipcTarget: "io.github.frestina.machines"
  // Own the target so it can carry refresh alongside open/close/toggle.
  manageIpc: false

  property var machines: []
  property bool loading: false
  property string error: ""
  property var checkedAt: null
  // Per run: a binary that fails to start only flips proc.running, with no
  // exited or stream signals, so finish() keys off running and these.
  property bool procStarted: false
  property int procExitCode: 0
  // A refresh-now that arrived mid-run (Unix seconds), replayed once it ends.
  property real pendingSince: 0

  readonly property string command: decodeURIComponent(Qt.resolvedUrl("bin/machines").toString().replace(/^file:\/\//, ""))
  readonly property int refreshSec: Math.max(60, Number(setting("refreshIntervalSec", 600)) || 600)

  readonly property var needAttention: machines.filter(function(m) {
    return m.view && m.view.status !== "ok"
  })
  // bad and down outrank warn; the bar icon turns urgent only for those.
  readonly property bool urgent: error !== "" || machines.some(function(m) {
    return m.view && (m.view.status === "bad" || m.view.status === "down")
  })

  readonly property string statusText: {
    if (loading && machines.length === 0) return "Checking…"
    if (error !== "") return "Check failed"
    if (needAttention.length === 0) return "All good"
    return needAttention.length + (needAttention.length === 1 ? " needs" : " need") + " attention"
  }

  readonly property string tooltipText: {
    if (error !== "") return "Machines: " + error
    if (needAttention.length === 0) return "Machines: all good"
    return "Machines: " + needAttention.map(function(m) { return m.label }).join(", ")
  }

  // maxAge lets every monitor's copy of this widget share one collection:
  // `machines` holds a lock and serves its cached result while it is fresh.
  function refresh(maxAge) {
    root.check(["--max-age", String(maxAge === undefined ? root.refreshSec - 30 : maxAge)])
  }

  // Collect unless a collection started at or after `since` (Unix seconds).
  function refreshSince(since) {
    if (proc.running) {
      pendingSince = Math.max(pendingSince, since)
      return
    }
    root.check(["--since", String(since)])
  }

  // Refresh every monitor's copy with one shared timestamp: the first to get
  // the lock collects and the rest read its result, instead of each forcing
  // its own collection.
  function refreshNow() {
    var since = Date.now() / 1000
    var items = root.bar && typeof root.bar.moduleWidgets === "function"
      ? root.bar.moduleWidgets(root.moduleName) : []
    if (items.indexOf(root) < 0) items = items.concat([root])
    for (var i = 0; i < items.length; i++)
      if (items[i] && typeof items[i].refreshSince === "function") items[i].refreshSince(since)
  }

  function check(args) {
    if (proc.running) return
    loading = true
    procStarted = false
    procExitCode = 0
    proc.command = [root.command, "--json"].concat(args)
    proc.running = true
  }

  function finish() {
    loading = false
    if (!procStarted) {
      error = "could not run " + root.command
    } else {
      var reason = errOut.text.trim().split("\n").pop()
      try {
        if (procExitCode !== 0) throw new Error(reason || "`machines --json` exited " + procExitCode)
        var data = JSON.parse(out.text)
        if (!Array.isArray(data)) throw new Error("unexpected output from `machines --json`")
        machines = data
        error = ""
        checkedAt = new Date()
      } catch (e) {
        error = e.message || reason || "`machines --json` failed"
      }
    }
    if (pendingSince > 0) {
      var since = pendingSince
      pendingSince = 0
      Qt.callLater(root.refreshSince, since)
    }
  }

  // Plugins get a scoped bar facade with run() but no shellQuote(); quote here.
  function openTable() {
    if (root.bar) root.bar.run("omarchy-launch-floating-terminal-with-presentation " + Util.shellQuote(root.command))
  }

  function ssh(machine) {
    if (!root.bar || machine.local) return
    root.close()
    root.bar.run("omarchy-launch-tui --app-id=org.omarchy.ssh ssh -- " + Util.shellQuote(machine.target))
  }

  // Muted text as see-through bar foreground, so it recedes on light and dark
  // themes alike (Qt.darker only mutes light-on-dark).
  function dim(alpha) {
    return Qt.rgba(root.barForeground.r, root.barForeground.g, root.barForeground.b, alpha)
  }

  function statusColor(status) {
    if (status === "bad" || status === "down") return Color.urgent
    if (status === "warn") return Color.accent
    return root.dim(0.35)
  }

  function column(machine, name) {
    var c = machine.view && machine.view.columns ? machine.view.columns[name] : null
    return c ? c.text : ""
  }

  function statsLine(machine) {
    if (machine.error) return "unreachable"
    var parts = ["load " + column(machine, "LOAD"), "mem " + column(machine, "MEM"),
                 "disk " + column(machine, "DISK /").split(" ")[0]]
    var updates = column(machine, "UPDATES")
    // The reboot note in this column is also an issue line of its own.
    updates = updates.replace(" aur", "").replace(", reboot", "")
    if (updates !== "" && updates !== "0") parts.push(updates + " updates")
    return parts.join(" · ")
  }

  onOpenedChanged: {
    // Opening shows whatever is cached at once; refresh if it is getting old.
    if (opened && (!checkedAt || Date.now() - checkedAt.getTime() > 60000)) refresh(60)
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    // The target routes to one instance; refreshNow() relays to the others.
    function refresh(): void { root.refreshNow() }
  }

  // Both streams finish and exited fires before running drops, so finish()
  // sees this run's complete output.
  Process {
    id: proc
    onStarted: root.procStarted = true
    onExited: function(exitCode) { root.procExitCode = exitCode }
    onRunningChanged: if (!running) root.finish()
    stdout: StdioCollector { id: out; waitForEnd: true }
    stderr: StdioCollector { id: errOut; waitForEnd: true }
  }

  Timer {
    interval: root.refreshSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.needAttention.length > 0 && !vertical ? "󰒋 " + root.needAttention.length : "󰒋"
    slotSize: Style.bar.iconSlot * (root.needAttention.length > 0 && !vertical ? 1.6 : 1)
    active: root.urgent
    dimmed: !root.urgent && root.needAttention.length === 0 && root.error === ""
    tooltipText: root.opened ? "" : root.tooltipText
    onPressed: function(b) {
      if (b === Qt.RightButton) root.openTable()
      else if (b === Qt.MiddleButton) root.refreshNow()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) { if (t === "r") root.refreshNow() }

      Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(12)

        // ---------- Hero: icon · title/status · actions ----------
        RowLayout {
          width: parent.width
          spacing: Style.space(12)

          Text {
            text: "󰒋"
            color: root.urgent ? Color.urgent : root.barForeground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.display
          }

          Column {
            Layout.fillWidth: true
            spacing: Style.space(2)

            Text {
              text: "Machines"
              color: root.barForeground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Text {
              textFormat: Text.PlainText
              text: (root.loading ? "Checking… " : root.statusText + (root.checkedAt
                ? " · " + Qt.formatTime(root.checkedAt, "HH:mm") : "")).toUpperCase()
              color: root.error !== "" ? Color.urgent : root.dim(0.6)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.2
              elide: Text.ElideRight
              width: parent.width
            }
          }

          PanelActionButton {
            iconText: "󰑐"
            tooltipText: "Check now (r)"
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
            enabled: !root.loading
            onClicked: root.refreshNow()
          }

          PanelActionButton {
            iconText: "󰆍"
            tooltipText: "Full table in a terminal"
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
            onClicked: { root.close(); root.openTable() }
          }
        }

        Text {
          visible: root.error !== ""
          width: parent.width
          textFormat: Text.PlainText
          text: root.error
          wrapMode: Text.Wrap
          color: Color.urgent
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        PanelSeparator { foreground: root.barForeground }

        // ---------- One block per machine ----------
        Repeater {
          model: root.machines

          delegate: Rectangle {
            id: machineRow
            required property var modelData
            readonly property var issues: modelData.view ? modelData.view.issues : []

            width: content.width
            implicitHeight: rowColumn.implicitHeight + Style.space(12)
            radius: Style.cornerRadius
            color: rowMouse.containsMouse && !modelData.local
              ? root.dim(0.06)
              : "transparent"

            MouseArea {
              id: rowMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: machineRow.modelData.local ? Qt.ArrowCursor : Qt.PointingHandCursor
              onClicked: root.ssh(machineRow.modelData)
            }

            Column {
              id: rowColumn
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: Style.space(6)
              anchors.rightMargin: Style.space(6)
              spacing: Style.space(3)

              RowLayout {
                width: parent.width
                spacing: Style.space(8)

                Rectangle {
                  implicitWidth: Style.space(8)
                  implicitHeight: Style.space(8)
                  radius: width / 2
                  color: root.statusColor(machineRow.modelData.view ? machineRow.modelData.view.status : "down")
                }

                Text {
                  Layout.fillWidth: true
                  textFormat: Text.PlainText
                  text: machineRow.modelData.label + (machineRow.modelData.local ? "  (this machine)" : "")
                  color: root.barForeground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                  elide: Text.ElideRight
                }

                Text {
                  textFormat: Text.PlainText
                  text: machineRow.modelData.error ? "" : "up " + root.column(machineRow.modelData, "UP")
                  color: root.dim(0.6)
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Text {
                width: parent.width
                leftPadding: Style.space(16)
                textFormat: Text.PlainText
                text: root.statsLine(machineRow.modelData)
                color: root.dim(0.6)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }

              Repeater {
                model: machineRow.issues

                delegate: Text {
                  required property var modelData
                  width: rowColumn.width
                  leftPadding: Style.space(16)
                  textFormat: Text.PlainText
                  text: "• " + modelData.text
                  wrapMode: Text.Wrap
                  color: modelData.severity === "bad" ? Color.urgent : root.barForeground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
              }
            }
          }
        }

        Text {
          visible: root.machines.some(function(m) { return !m.local })
          width: parent.width
          textFormat: Text.PlainText
          text: "Click a machine to ssh in"
          horizontalAlignment: Text.AlignHCenter
          color: root.dim(0.45)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
