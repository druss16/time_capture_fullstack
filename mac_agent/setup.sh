#!/bin/bash

# TimeTracker Setup & Launcher Script
# This script helps set up and launch the TimeTracker agent with GUI

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_DIR="$HOME/.timetracker"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$LAUNCH_AGENT_DIR/com.timetracker.agent.plist"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check if Python 3 is installed
check_python() {
    print_step "Checking Python installation..."
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        echo "Please install Python 3: brew install python3"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python $PYTHON_VERSION found"
}

# Check/install PyObjC
check_pyobjc() {
    print_step "Checking PyObjC installation..."
    
    if python3 -c "import objc" 2>/dev/null; then
        print_success "PyObjC is installed"
    else
        print_warning "PyObjC not found. Installing..."
        pip3 install --user pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-UserNotifications
        print_success "PyObjC installed"
    fi
}

# Create config directory
setup_config() {
    print_step "Setting up configuration..."
    
    mkdir -p "$CONFIG_DIR"
    
    if [ ! -f "$CONFIG_DIR/config.json" ]; then
        cat > "$CONFIG_DIR/config.json" << 'EOF'
{
  "api_base": "http://localhost:7123/api",
  "poll_seconds": 5,
  "min_dwell_seconds": 15,
  "nudge_enabled": true,
  "verbose": true
}
EOF
        print_success "Created default config.json"
    else
        print_success "config.json already exists"
    fi
    
    # Create clients file with samples if it doesn't exist
    if [ ! -f "$CONFIG_DIR/clients.json" ]; then
        cat > "$CONFIG_DIR/clients.json" << 'EOF'
[
  {
    "id": 1,
    "name": "Sample Client A",
    "code": "SMPA"
  },
  {
    "id": 2,
    "name": "Sample Client B",
    "code": "SMPB"
  }
]
EOF
        print_success "Created sample clients.json"
    fi
}

# Create LaunchAgent plist
create_launch_agent() {
    print_step "Setting up LaunchAgent for auto-start..."
    
    mkdir -p "$LAUNCH_AGENT_DIR"
    
    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.timetracker.agent</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>$SCRIPT_DIR/main.py</string>
        <string>start</string>
    </array>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/timetracker.log</string>
    
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/timetracker.error.log</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF
    
    print_success "Created LaunchAgent plist"
}

# Request accessibility permissions
request_permissions() {
    print_step "Checking Accessibility permissions..."
    
    print_warning "TimeTracker needs Accessibility permissions to track window titles"
    echo ""
    echo "Please:"
    echo "  1. Open System Settings (or System Preferences)"
    echo "  2. Go to Privacy & Security → Accessibility"
    echo "  3. Add Terminal (or your terminal app) to the list"
    echo "  4. Also add Python if it appears"
    echo ""
    read -p "Press Enter when you've granted permissions..."
}

# Usage information
show_usage() {
    cat << 'EOF'

╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║                   🕐 TimeTracker Setup 🕐                     ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝

COMMANDS:
  ./setup.sh install     - Install dependencies and configure
  ./setup.sh start       - Start TimeTracker agent with GUI
  ./setup.sh stop        - Stop TimeTracker agent
  ./setup.sh restart     - Restart TimeTracker agent
  ./setup.sh status      - Check if agent is running
  ./setup.sh autostart   - Enable auto-start on login
  ./setup.sh logs        - View agent logs

MANUAL RUN:
  python3 main.py start  - Run in foreground with logs

CONFIGURATION:
  Config file:  ~/.timetracker/config.json
  Clients file: ~/.timetracker/clients.json
  Logs:         ~/Library/Logs/timetracker.log

FEATURES:
  ⏱  Menu bar icon showing current client
  🪟 Floating prompt window for AI suggestions
  📊 View today's tracked time by client
  ✏️  Manage clients (add/edit/delete)
  🎯 Switch clients manually

EOF
}

# Install command
cmd_install() {
    print_step "Installing TimeTracker..."
    echo ""
    
    check_python
    check_pyobjc
    setup_config
    request_permissions
    
    echo ""
    print_success "Installation complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Edit ~/.timetracker/config.json with your API base URL"
    echo "  2. Run: ./setup.sh start"
    echo ""
}

# Start command
cmd_start() {
    print_step "Starting TimeTracker..."
    
    # Check if already running
    if pgrep -f "python.*main.py" > /dev/null; then
        print_warning "TimeTracker is already running"
        exit 0
    fi
    
    cd "$SCRIPT_DIR"
    python3 main.py start &
    
    sleep 2
    
    if pgrep -f "python.*main.py" > /dev/null; then
        print_success "TimeTracker started successfully"
        echo "Check the menu bar for the timer icon (⏱)"
    else
        print_error "Failed to start TimeTracker"
        exit 1
    fi
}

# Stop command
cmd_stop() {
    print_step "Stopping TimeTracker..."
    
    if pgrep -f "python.*main.py" > /dev/null; then
        python3 "$SCRIPT_DIR/main.py" stop
        sleep 1
        print_success "TimeTracker stopped"
    else
        print_warning "TimeTracker is not running"
    fi
}

# Status command
cmd_status() {
    print_step "Checking TimeTracker status..."
    
    if pgrep -f "python.*main.py" > /dev/null; then
        PID=$(pgrep -f "python.*main.py")
        print_success "TimeTracker is running (PID: $PID)"
        
        # Check current client
        if [ -f "$CONFIG_DIR/gui_state.json" ]; then
            CLIENT=$(python3 -c "import json; print(json.load(open('$CONFIG_DIR/gui_state.json')).get('current_client_name', 'Unknown'))" 2>/dev/null || echo "Unknown")
            echo "  Current client: $CLIENT"
        fi
    else
        print_warning "TimeTracker is not running"
    fi
}

# Restart command
cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

# Enable autostart
cmd_autostart() {
    print_step "Enabling auto-start on login..."
    
    create_launch_agent
    
    # Load the LaunchAgent
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load "$PLIST_FILE"
    
    print_success "Auto-start enabled"
    print_warning "TimeTracker will start automatically on next login"
}

# View logs
cmd_logs() {
    LOGFILE="$HOME/Library/Logs/timetracker.log"
    
    if [ -f "$LOGFILE" ]; then
        print_step "Showing recent logs (Ctrl+C to exit)..."
        tail -f "$LOGFILE"
    else
        print_warning "No log file found at $LOGFILE"
        echo "Run TimeTracker first to generate logs"
    fi
}

# Main script logic
case "${1:-}" in
    install)
        cmd_install
        ;;
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    autostart)
        cmd_autostart
        ;;
    logs)
        cmd_logs
        ;;
    *)
        show_usage
        ;;
esac