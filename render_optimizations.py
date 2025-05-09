import gc

def optimize_for_render(app):
    """Apply optimizations for Render.com environment"""
    # Memory optimization settings
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = False
    app.config['PRESERVE_CONTEXT_ON_EXCEPTION'] = False
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
    
    # Set SQLAlchemy pool settings
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 5,
        'max_overflow': 10,
        'pool_recycle': 1800,
        'pool_pre_ping': True
    }
    
    # Register memory-saving hooks
    @app.after_request
    def cleanup_response(response):
        gc.collect(0)  # Quick collection of youngest generation objects
        return response
    
    return app
