from app import app, db, User, Container, ContainerStatus, Vessel, ContainerMovement
import sys

def show_database_status():
    with app.app_context():
        num_users = User.query.count()
        num_containers = Container.query.count()
        num_vessel = Vessel.query.count()
        num_statuses = ContainerStatus.query.count()
        num_movements = ContainerMovement.query.count()
        
        print(f"Database Status:")
        print(f"---------------")
        print(f"Users: {num_users}")
        print(f"Containers: {num_containers}")
        print(f"Vessels: {num_vessel}")
        print(f"Container Statuses: {num_statuses}")
        print(f"Container Movements: {num_movements}")
        
        # Show admin users
        admin_users = User.query.filter_by(is_admin=True).all()
        if admin_users:
            print("\nAdmin Users:")
            for user in admin_users:
                print(f" - {user.username} ({user.email})")
        
        # Show regular users
        regular_users = User.query.filter_by(is_admin=False).all()
        if regular_users:
            print("\nRegular Users:")
            for user in regular_users:
                print(f" - {user.username} ({user.email})")

if __name__ == '__main__':
    show_database_status()
