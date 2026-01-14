"""
sync_manager.py - Desktop Agent Sync System
Handles efficient synchronization between agent and TimeTracker server.

Features:
- Smart polling (only fetches when data changed)
- Local caching with SQLite
- Background sync thread
- Event callbacks for UI updates
"""

import json
import sqlite3
import threading
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, List, Any
from dataclasses import dataclass, asdict
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


@dataclass
class Client:
    id: int
    name: str
    code: str
    visibility: str
    my_role: Optional[str] = None


@dataclass
class Project:
    id: int
    name: str
    code: str
    client_id: int
    client_name: str


@dataclass
class TaskType:
    id: int
    name: str
    code: str
    is_billable: bool


class SyncManager:
    """
    Manages synchronization between desktop agent and TimeTracker server.
    
    Usage:
        sync = SyncManager(api_base_url, auth_token, cache_dir)
        sync.on_clients_updated = lambda clients: update_ui(clients)
        sync.start()  # Starts background polling
        
        # Access cached data anytime
        clients = sync.get_clients()
        
        # Force refresh
        sync.refresh_now()
        
        # Stop when app closes
        sync.stop()
    """
    
    def __init__(
        self, 
        api_base: str, 
        auth_token: str, 
        cache_dir: Optional[Path] = None,
        poll_interval: int = 60  # seconds
    ):
        self.api_base = api_base.rstrip('/')
        self.auth_token = auth_token
        self.poll_interval = poll_interval
        
        # Cache directory
        if cache_dir is None:
            cache_dir = Path.home() / '.timetracker'
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_db = cache_dir / 'sync_cache.db'
        
        # Initialize SQLite cache
        self._init_cache_db()
        
        # Sync state
        self._hashes: Dict[str, str] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_sync: Optional[datetime] = None
        self._lock = threading.Lock()
        
        # Event callbacks
        self.on_clients_updated: Optional[Callable[[List[Client]], None]] = None
        self.on_projects_updated: Optional[Callable[[List[Project]], None]] = None
        self.on_task_types_updated: Optional[Callable[[List[TaskType]], None]] = None
        self.on_sync_complete: Optional[Callable[[], None]] = None
        self.on_sync_error: Optional[Callable[[str], None]] = None
    
    # ==========================================================================
    # Public API
    # ==========================================================================
    
    def start(self):
        """Start background sync thread"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        logger.info("Sync manager started")
    
    def stop(self):
        """Stop background sync thread"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Sync manager stopped")
    
    def refresh_now(self):
        """Force immediate sync"""
        threading.Thread(target=self._do_sync, daemon=True).start()
    
    def get_clients(self) -> List[Client]:
        """Get cached clients list"""
        return self._load_from_cache('clients', Client)
    
    def get_projects(self, client_id: Optional[int] = None) -> List[Project]:
        """Get cached projects list, optionally filtered by client"""
        projects = self._load_from_cache('projects', Project)
        if client_id:
            projects = [p for p in projects if p.client_id == client_id]
        return projects
    
    def get_task_types(self) -> List[TaskType]:
        """Get cached task types list"""
        return self._load_from_cache('task_types', TaskType)
    
    def get_client_by_id(self, client_id: int) -> Optional[Client]:
        """Get single client by ID"""
        clients = self.get_clients()
        return next((c for c in clients if c.id == client_id), None)
    
    def get_client_by_name(self, name: str) -> Optional[Client]:
        """Get single client by name (case-insensitive)"""
        clients = self.get_clients()
        name_lower = name.lower()
        return next((c for c in clients if c.name.lower() == name_lower), None)
    
    @property
    def last_sync(self) -> Optional[datetime]:
        """When was the last successful sync"""
        return self._last_sync
    
    @property
    def is_running(self) -> bool:
        """Is background sync running"""
        return self._running
    
    # ==========================================================================
    # Sync Logic
    # ==========================================================================
    
    def _sync_loop(self):
        """Background polling loop"""
        # Initial full sync
        self._do_full_sync()
        
        while self._running:
            try:
                time.sleep(self.poll_interval)
                if self._running:
                    self._do_sync()
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                if self.on_sync_error:
                    self.on_sync_error(str(e))
    
    def _do_sync(self):
        """Check for changes and sync what's needed"""
        try:
            # Get sync status from server
            status = self._api_get('/sync/status/')
            if not status:
                return
            
            entities = status.get('entities', {})
            changes = []
            
            # Check each entity type for changes
            for entity_type in ['clients', 'projects', 'task_types']:
                entity_data = entities.get(entity_type, {})
                new_hash = entity_data.get('hash', '')
                old_hash = self._hashes.get(entity_type, '')
                
                if new_hash and new_hash != old_hash:
                    changes.append(entity_type)
                    self._hashes[entity_type] = new_hash
            
            # Fetch changed entities
            for entity_type in changes:
                logger.info(f"Syncing {entity_type}...")
                self._sync_entity(entity_type)
            
            self._last_sync = datetime.now()
            
            if changes and self.on_sync_complete:
                self.on_sync_complete()
                
        except Exception as e:
            logger.error(f"Sync error: {e}")
            if self.on_sync_error:
                self.on_sync_error(str(e))
    
    def _do_full_sync(self):
        """Full sync - fetch everything"""
        try:
            logger.info("Starting full sync...")
            data = self._api_get('/sync/full/')
            if not data:
                return
            
            # Save to cache
            self._save_to_cache('clients', data.get('clients', []))
            self._save_to_cache('projects', data.get('projects', []))
            self._save_to_cache('task_types', data.get('task_types', []))
            
            # Update hashes (we'll get real ones on next status check)
            self._hashes = {}
            
            self._last_sync = datetime.now()
            
            # Trigger callbacks
            if self.on_clients_updated:
                self.on_clients_updated(self.get_clients())
            if self.on_projects_updated:
                self.on_projects_updated(self.get_projects())
            if self.on_task_types_updated:
                self.on_task_types_updated(self.get_task_types())
            if self.on_sync_complete:
                self.on_sync_complete()
                
            logger.info("Full sync complete")
            
        except Exception as e:
            logger.error(f"Full sync error: {e}")
            if self.on_sync_error:
                self.on_sync_error(str(e))
    
    def _sync_entity(self, entity_type: str):
        """Sync a specific entity type"""
        endpoint_map = {
            'clients': '/sync/clients/',
            'projects': '/sync/projects/',
            'task_types': '/sync/task-types/',
        }
        
        callback_map = {
            'clients': self.on_clients_updated,
            'projects': self.on_projects_updated,
            'task_types': self.on_task_types_updated,
        }
        
        endpoint = endpoint_map.get(entity_type)
        if not endpoint:
            return
        
        data = self._api_get(endpoint)
        if not data:
            return
        
        # Save to cache
        items = data.get(entity_type, [])
        self._save_to_cache(entity_type, items)
        
        # Trigger callback
        callback = callback_map.get(entity_type)
        if callback:
            getter_map = {
                'clients': self.get_clients,
                'projects': self.get_projects,
                'task_types': self.get_task_types,
            }
            callback(getter_map[entity_type]())
    
    # ==========================================================================
    # API Helpers
    # ==========================================================================
    
    def _api_get(self, endpoint: str) -> Optional[Dict]:
        """Make authenticated GET request"""
        url = f"{self.api_base}{endpoint}"
        
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'Bearer {self.auth_token}')
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            logger.error(f"API error {e.code}: {endpoint}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"Network error: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None
    
    # ==========================================================================
    # Cache Management
    # ==========================================================================
    
    def _init_cache_db(self):
        """Initialize SQLite cache database"""
        with sqlite3.connect(self.cache_db) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT,
                    updated_at TEXT
                )
            ''')
            conn.commit()
    
    def _save_to_cache(self, key: str, data: List[Dict]):
        """Save data to cache"""
        with self._lock:
            with sqlite3.connect(self.cache_db) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO cache (key, data, updated_at)
                    VALUES (?, ?, ?)
                ''', (key, json.dumps(data), datetime.now().isoformat()))
                conn.commit()
    
    def _load_from_cache(self, key: str, dataclass_type) -> List:
        """Load data from cache and convert to dataclass instances"""
        with self._lock:
            with sqlite3.connect(self.cache_db) as conn:
                cursor = conn.execute(
                    'SELECT data FROM cache WHERE key = ?', 
                    (key,)
                )
                row = cursor.fetchone()
                
        if not row:
            return []
        
        try:
            items = json.loads(row[0])
            return [dataclass_type(**item) for item in items]
        except Exception as e:
            logger.error(f"Cache parse error for {key}: {e}")
            return []
    
    def clear_cache(self):
        """Clear all cached data"""
        with self._lock:
            with sqlite3.connect(self.cache_db) as conn:
                conn.execute('DELETE FROM cache')
                conn.commit()
        self._hashes = {}


# ==============================================================================
# Example Usage
# ==============================================================================

if __name__ == '__main__':
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    API_BASE = 'https://timetracker-api-k375.onrender.com/api'
    AUTH_TOKEN = 'your-auth-token-here'
    
    # Create sync manager
    sync = SyncManager(API_BASE, AUTH_TOKEN)
    
    # Set up callbacks for UI updates
    def on_clients_changed(clients):
        print(f"\n📋 Clients updated ({len(clients)} total):")
        for c in clients[:5]:
            print(f"  - {c.name} ({c.code or 'no code'})")
        if len(clients) > 5:
            print(f"  ... and {len(clients) - 5} more")
    
    def on_sync_complete():
        print(f"\n✅ Sync complete at {sync.last_sync}")
    
    def on_sync_error(error):
        print(f"\n❌ Sync error: {error}")
    
    sync.on_clients_updated = on_clients_changed
    sync.on_sync_complete = on_sync_complete
    sync.on_sync_error = on_sync_error
    
    # Start background sync
    sync.start()
    
    # Keep running
    try:
        print("Sync manager running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sync.stop()
        print("\nStopped.")