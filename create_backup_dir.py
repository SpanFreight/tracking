import os

def create_backup_directory():
    """Create a directory to store database backups"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(current_dir, 'backups')
    
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        print(f"Created backup directory at: {backup_dir}")
    else:
        print(f"Backup directory already exists at: {backup_dir}")

if __name__ == "__main__":
    create_backup_directory()
