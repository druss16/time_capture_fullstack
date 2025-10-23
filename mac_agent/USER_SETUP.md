# TimeTracker Agent - User Setup

## Installation

### 1. Download the Agent
- Download `TimeTracker.app` (or `TimeTracker` executable)
- Move it to your Applications folder

### 2. Configure the Agent

Create a config file at `~/.timetracker/config.json`:

```bash
mkdir -p ~/.timetracker
```

Copy the example config and edit it:

```bash
cat > ~/.timetracker/config.json << 'EOF'
{
  "api_url": "https://api.yourdomain.com/api/raw-events/",
  "api_key": "your-personal-api-key",
  "min_dwell_seconds": 15,
  "poll_seconds": 5,
  "verbose": true
}
EOF
```

**Replace:**
- `api_url` - Your company's API endpoint
- `api_key` - Your personal API key (get from account settings)

### 3. Grant Permissions

macOS will prompt for permissions when you first run the agent:

1. **Accessibility** - Required for window titles
   - Go to: System Settings → Privacy & Security → Accessibility
   - Enable for TimeTracker

2. **Automation** (optional) - For browser URLs
   - Prompts automatically when needed
   - Enable for Safari/Chrome/Brave access

### 4. Run the Agent

```bash
# Manual run (for testing)
/Applications/TimeTracker.app/Contents/MacOS/TimeTracker

# Or double-click TimeTracker.app
```

### 5. Auto-Start on Login (Optional)

To run automatically when you log in, install the LaunchAgent:

```bash
cp com.mavops.activityagent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mavops.activityagent.plist
```

## Configuration Options

All options in `~/.timetracker/config.json`:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `api_url` | string | (required) | Your API endpoint URL |
| `api_key` | string | (required) | Your personal API key |
| `min_dwell_seconds` | number | 15 | Minimum time on a window before logging |
| `poll_seconds` | number | 5 | How often to check for window changes |
| `verbose` | boolean | true | Show detailed logs |
| `print_every` | boolean | false | Log every poll (very verbose) |
| `disable_ax` | boolean | false | Disable Accessibility API |
| `exclude_bundles` | array | [] | Bundle IDs to ignore (e.g., `["com.apple.Terminal"]`) |

## Troubleshooting

### Agent not sending data?
- Check config file exists: `cat ~/.timetracker/config.json`
- Verify API URL is correct
- Check API key is valid
- Run with verbose mode to see POST attempts

### Can't see window titles?
- Grant Accessibility permission
- Restart the agent after granting permissions

### Browser URLs not working?
- Grant Automation permission when prompted
- Check System Settings → Privacy & Security → Automation

### Check if agent is running
```bash
ps aux | grep TimeTracker
```

### View local database
```bash
sqlite3 ~/Library/ActivityAgent/agent.sqlite3 "SELECT * FROM raw_events ORDER BY ts_utc DESC LIMIT 10;"
```

## Uninstall

```bash
# Stop the agent
launchctl unload ~/Library/LaunchAgents/com.mavops.activityagent.plist

# Remove files
rm -rf /Applications/TimeTracker.app
rm ~/Library/LaunchAgents/com.mavops.activityagent.plist
rm -rf ~/.timetracker
rm -rf ~/Library/ActivityAgent
```

## Support

Contact: support@yourdomain.com