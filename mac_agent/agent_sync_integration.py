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
        logger.info("Agent sync started")
    
    def stop(self):
        """Stop background sync"""
        self._running = False
        logger.info("Agent sync stopped")
    
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
        # Initial sync
        self._full_sync()
        
        while self._running:
            time.sleep(self.poll_interval)
            if self._running:
                self._check_and_sync()
    
    def _check_and_sync(self):
        """Check for changes, sync if needed"""
        try:
            status = self._get('/sync/status/')
            if not status:
                return
            
            entities = status.get('entities', {})
            needs_sync = False
            
            for key in ['clients', 'projects', 'task_types']:
                new_hash = entities.get(key, {}).get('hash', '')
                if new_hash and new_hash != self._hashes.get(key):
                    needs_sync = True
                    self._hashes[key] = new_hash
            
            if needs_sync:
                self._full_sync()
                
        except Exception as e:
            logger.error(f"Sync check error: {e}")
    
    def _full_sync(self):
        """Fetch all data from server"""
        try:
            data = self._get('/sync/full/')
            if not data:
                return
            
            self.clients = data.get('clients', [])
            self.projects = data.get('projects', [])
            self.task_types = data.get('task_types', [])
            self.last_sync = datetime.now()
            
            self._save_cache()
            
            logger.info(f"Synced: {len(self.clients)} clients, {len(self.projects)} projects")
            
            if self.on_update:
                self.on_update()
                
        except Exception as e:
            logger.error(f"Full sync error: {e}")
            if self.on_error:
                self.on_error(str(e))
    
    def _get(self, endpoint: str) -> Optional[Dict]:
        """Make API request"""
        url = f"{self.api_base}{endpoint}"
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'Bearer {self.device_token}')
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"API error: {e}")
            return None
    
    def _save_cache(self):
        """Save to disk"""
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cache_file, 'w') as f:
            json.dump({
                'clients': self.clients,
                'projects': self.projects,
                'task_types': self.task_types,
                'hashes': self._hashes,
            }, f)
    
    def _load_cache(self):
        """Load from disk"""
        if self._cache_file.exists():
            try:
                with open(self._cache_file) as f:
                    data = json.load(f)
                self.clients = data.get('clients', [])
                self.projects = data.get('projects', [])
                self.task_types = data.get('task_types', [])
                self._hashes = data.get('hashes', {})
            except Exception as e:
                logger.error(f"Cache load error: {e}")