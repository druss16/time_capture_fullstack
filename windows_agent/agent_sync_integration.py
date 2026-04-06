import json
import threading
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Callable
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


def log(msg: str):
    """Print with timestamp for visibility"""
    print(msg, flush=True)


class AgentSync:
    """
    Simple sync manager for TimeTracker agent.
    
    Quick Start:
        sync = AgentSync(api_base, device_token)
        sync.start()
        
        # Get data anytime
        clients = sync.clients
        projects = sync.projects
        
        # React to updates
        sync.on_update = lambda: refresh_dropdown()
    """
    
    def __init__(self, api_base: str, device_token: str):
        self.api_base = api_base.rstrip('/')
        self.device_token = device_token
        
        # Cached data
        self.clients: List[Dict] = []
        self.projects: List[Dict] = []
        self.task_types: List[Dict] = []
        self.client_patterns: List[Dict] = []
        self.org_settings: Dict = {}
        
        # State
        self._hashes: Dict[str, str] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.last_sync: Optional[datetime] = None
        
        # Callbacks
        self.on_update: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        
        # Settings
        self.poll_interval = 60  # seconds
        
        # Load from disk cache
        self._cache_file = Path.home() / '.timetracker' / 'sync_cache.json'
        self._load_cache()
    
    # ==========================================================================
    # Public Methods
    # ==========================================================================
    
    def start(self):
        """Start background sync"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log("[SYNC] Background thread started")
    
    def stop(self):
        """Stop background sync"""
        self._running = False
        log("[SYNC] Stopped")
    
    def refresh(self):
        """Force immediate refresh"""
        threading.Thread(target=self._full_sync, daemon=True).start()
    
    def get_client(self, client_id: int) -> Optional[Dict]:
        """Get client by ID"""
        return next((c for c in self.clients if c['id'] == client_id), None)
    
    def get_client_by_name(self, name: str) -> Optional[Dict]:
        """Get client by name (case-insensitive)"""
        name_lower = name.lower()
        return next((c for c in self.clients if c['name'].lower() == name_lower), None)
    
    def get_projects_for_client(self, client_id: int) -> List[Dict]:
        """Get projects for a specific client"""
        return [p for p in self.projects if p['client_id'] == client_id]
    
    # ==========================================================================
    # Internal
    # ==========================================================================
    
    def _run(self):
        """Background sync loop"""
        log("[SYNC] Initial sync starting...")
        self._full_sync()
        
        while self._running:
            time.sleep(self.poll_interval)
            if self._running:
                self._check_and_sync()
    
    def _check_and_sync(self):
        """Check for changes, sync if needed"""
        try:
            log("[SYNC] Checking for updates...")
            status = self._get('/sync/status/')
            if not status:
                log("[SYNC] Status check failed (no response)")
                return
            
            entities = status.get('entities', {})
            needs_sync = False
            changed_entities = []
            
            for key in ['clients', 'projects', 'task_types', 'client_patterns']:
                new_hash = entities.get(key, {}).get('hash', '')
                old_hash = self._hashes.get(key, '')
                if new_hash and new_hash != old_hash:
                    needs_sync = True
                    changed_entities.append(key)
                    self._hashes[key] = new_hash
            
            if needs_sync:
                log(f"[SYNC] Changes detected in: {', '.join(changed_entities)}")
                self._full_sync()
            else:
                log("[SYNC] No changes detected")
                
        except Exception as e:
            log(f"[SYNC] Check error: {e}")
    
    def _full_sync(self):
        """Fetch all data from server"""
        try:
            data = self._get('/sync/full/')
            if not data:
                log("[SYNC] Full sync failed (no response)")
                return
            
            self.clients = data.get('clients', [])
            self.projects = data.get('projects', [])
            self.task_types = data.get('task_types', [])
            self.client_patterns = data.get('client_patterns', [])   # ← NEW
            self.org_settings = data.get('org_settings', {})          # ← NEW
            self.last_sync = datetime.now()
            
            # Update hashes from full sync if available
            # (prevents immediate re-sync)
            
            self._save_cache()
            
            log(f"[SYNC] Full sync complete: {len(self.clients)} clients, {len(self.projects)} projects")
            
            if self.on_update:
                self.on_update()
                
        except Exception as e:
            log(f"[SYNC] Full sync error: {e}")
            if self.on_error:
                self.on_error(str(e))
    
    def _get(self, endpoint: str) -> Optional[Dict]:
        """Make API request"""
        url = f"{self.api_base}{endpoint}"
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'DeviceKey {self.device_token}')
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            log(f"[SYNC] API error: HTTP {e.code} - {e.reason}")
            return None
        except urllib.error.URLError as e:
            log(f"[SYNC] Network error: {e.reason}")
            return None
        except Exception as e:
            log(f"[SYNC] Request error: {e}")
            return None
    
    def _save_cache(self):
        """Save to disk"""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_file, 'w') as f:
                json.dump({
                    'clients': self.clients,
                    'projects': self.projects,
                    'task_types': self.task_types,
                    'client_patterns': self.client_patterns,             # ← NEW
                    'org_settings': self.org_settings,                   # ← NEW
                    'hashes': self._hashes,
                }, f)
        except Exception as e:
            log(f"[SYNC] Cache save error: {e}")
    
    def _load_cache(self):
        """Load from disk"""
        if self._cache_file.exists():
            try:
                with open(self._cache_file) as f:
                    data = json.load(f)
                self.clients = data.get('clients', [])
                self.projects = data.get('projects', [])
                self.task_types = data.get('task_types', [])
                self.client_patterns = data.get('client_patterns', [])   # ← NEW
                self.org_settings = data.get('org_settings', {})          # ← NEW
                self._hashes = data.get('hashes', {})
                log(f"[SYNC] Loaded {len(self.clients)} clients from cache")
            except Exception as e:
                log(f"[SYNC] Cache load error: {e}")