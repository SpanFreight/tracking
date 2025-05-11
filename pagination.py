from flask import request, url_for

class Pagination:
    def __init__(self, query, page=1, per_page=25, endpoint=None, **kwargs):
        self.query = query
        self.page = page
        self.per_page = per_page
        self.endpoint = endpoint
        self.kwargs = kwargs
        
        # Apply pagination to query or list
        if hasattr(query, 'limit'):
            # SQLAlchemy query
            self.total = query.count()
            self.items = query.limit(per_page).offset((page - 1) * per_page).all()
        else:
            # Python list
            self.total = len(query)
            self.items = query[(page - 1) * per_page:page * per_page]
        
        # Calculate other pagination metadata
        self.pages = (self.total - 1) // self.per_page + 1 if self.total > 0 else 1
    
    @property
    def has_prev(self):
        return self.page > 1
    
    @property
    def has_next(self):
        return self.page < self.pages
    
    @property
    def prev_page(self):
        return self.page - 1
    
    @property
    def next_page(self):
        return self.page + 1
    
    def get_url(self, page):
        """Generate URL for a page"""
        if self.endpoint:
            args = dict(self.kwargs)
            args['page'] = page
            return url_for(self.endpoint, **args)
        return f"?page={page}"
