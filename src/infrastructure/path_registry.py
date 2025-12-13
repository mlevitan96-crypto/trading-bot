import os
from pathlib import Path

class PathRegistry:
    """
    Centralized registry for absolute path resolution.
    Ensures file access remains robust regardless of execution context.
    
    This solves the "relative path vulnerability" where logs/... paths
    fail in Reserved VM deployments due to different CWD contexts.
    
    Usage:
        from src.infrastructure.path_registry import PathRegistry
        
        # Get absolute path to a file
        log_path = PathRegistry.get_path("logs", "events.jsonl")
        
        # Ensure directory exists before writing
        file_path = PathRegistry.ensure_dir("logs", "subdir", "file.json")
        
        # Quick conversion from relative path string
        abs_path = resolve_path("logs/positions.json")
    """
    _CURRENT_FILE = Path(__file__).resolve()
    PROJECT_ROOT = _CURRENT_FILE.parent.parent.parent
    
    if not (PROJECT_ROOT / ".replit").exists():
        PROJECT_ROOT = Path(os.getenv("REPL_HOME", os.getcwd()))

    SRC_DIR = PROJECT_ROOT / "src"
    LOGS_DIR = PROJECT_ROOT / "logs"
    CONFIG_DIR = PROJECT_ROOT / "config"
    CONFIGS_DIR = PROJECT_ROOT / "configs"
    DATA_DIR = PROJECT_ROOT / "data"
    FEATURE_STORE_DIR = PROJECT_ROOT / "feature_store"
    BACKUPS_DIR = PROJECT_ROOT / "backups"
    LOGS_BACKUPS_DIR = LOGS_DIR / "backups"

    EVENTS_LOG = LOGS_DIR / "unified_events.jsonl"
    POS_LOG = LOGS_DIR / "positions_futures.json"
    PORTFOLIO_LOG = LOGS_DIR / "portfolio_futures.json"
    ACCOUNT_SNAP = LOGS_DIR / "accounting_snapshot.json"
    PROTECTIVE_MODE_LOG = LOGS_DIR / "protective_mode_log.json"
    SUPERVISOR_CONF = PROJECT_ROOT / "supervisord.conf"
    
    BOT_OUT_LOG = LOGS_DIR / "bot_out.log"
    BOT_ERR_LOG = LOGS_DIR / "bot_err.log"
    HEALTH_OUT_LOG = LOGS_DIR / "health_out.log"
    HEALTH_ERR_LOG = LOGS_DIR / "health_err.log"
    SUPERVISOR_LOG = LOGS_DIR / "supervisord.log"

    @classmethod
    def get_root(cls) -> Path:
        """Return the absolute path object to the project root."""
        return cls.PROJECT_ROOT
    
    @classmethod
    def get_path(cls, *path_segments: str) -> str:
        """
        Construct an absolute path from the project root.
        Usage: PathRegistry.get_path("logs", "unified_events.jsonl")
        
        Args:
            *path_segments: Strings representing folder/file names.
            
        Returns:
            str: The absolute path to the requested resource.
        """
        return str(cls.PROJECT_ROOT.joinpath(*path_segments))

    @classmethod
    def ensure_dir(cls, *path_segments: str) -> str:
        """
        Construct a path and ensure the parent directory exists.
        Useful for logging to ensure 'logs/' exists before writing.
        
        Args:
            *path_segments: Path segments (e.g., "logs", "subdir", "file.json")
            
        Returns:
            str: The absolute path with parent directory guaranteed to exist.
        """
        full_path = cls.get_path(*path_segments)
        if '.' in os.path.basename(full_path):
            dir_path = os.path.dirname(full_path)
        else:
            dir_path = full_path
        os.makedirs(dir_path, exist_ok=True)
        return full_path

    @classmethod
    def ensure_directories(cls):
        """Creates necessary directories if they don't exist."""
        for path in [cls.LOGS_DIR, cls.CONFIG_DIR, cls.CONFIGS_DIR, cls.DATA_DIR, 
                     cls.FEATURE_STORE_DIR, cls.BACKUPS_DIR, cls.LOGS_BACKUPS_DIR]:
            path.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def get_absolute_path(cls, relative_path: str) -> Path:
        """Convert a relative path to absolute based on PROJECT_ROOT."""
        return cls.PROJECT_ROOT / relative_path
    
    @classmethod
    def validate_environment(cls) -> dict:
        """Validate the environment is correctly configured."""
        return {
            "project_root": str(cls.PROJECT_ROOT),
            "root_exists": cls.PROJECT_ROOT.exists(),
            "replit_file_exists": (cls.PROJECT_ROOT / ".replit").exists(),
            "logs_dir_exists": cls.LOGS_DIR.exists(),
            "config_dir_exists": cls.CONFIG_DIR.exists(),
            "data_dir_exists": cls.DATA_DIR.exists(),
        }


def resolve_path(path_str: str) -> str:
    """
    Converts a relative path string (e.g., 'logs/file.json') to absolute.
    Splits by forward slash to handle cross-platform compatibility.
    
    Args:
        path_str: Relative path like "logs/positions.json"
        
    Returns:
        str: Absolute path
    """
    parts = path_str.split('/')
    return PathRegistry.get_path(*parts)
