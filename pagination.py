from flask import request, url_for

class Pagination:
    """Pagination helper class"""
    
    def __init__(self, items, page, per_page, endpoint, total=None, **kwargs):
        """Initialize pagination
        
        Args:
            items: The items to paginate (list or query)
            page: Current page number (1-indexed)
            per_page: Number of items per page
            endpoint: The endpoint for generating URLs
            total: Total number of items (optional, calculated from items if not provided)
            **kwargs: Additional URL parameters for pagination links
        """
        self.items = items
        self.page = page
        self.per_page = per_page
        self.endpoint = endpoint
        self.kwargs = kwargs
        
        if isinstance(items, list):
            # If items is a list, paginate it manually
            self.total = total or len(items)
            start_index = (page - 1) * per_page
            end_index = min(start_index + per_page, self.total)
            self.items = items[start_index:end_index]
        else:
            # If items is a query, it's already paginated
            self.total = total or len(items)
    
    @property
    def pages(self):
        """The total number of pages"""
        return max(1, (self.total + self.per_page - 1) // self.per_page)
    
    @property
    def has_prev(self):
        """True if a previous page exists"""
        return self.page > 1
    
    @property
    def has_next(self):
        """True if a next page exists"""
        return self.page < self.pages
    
    @property
    def prev_num(self):
        """Number of the previous page"""
        return self.page - 1 if self.has_prev else None
    
    @property
    def next_num(self):
        """Number of the next page"""
        return self.page + 1 if self.has_next else None
    
    def get_url(self, page):
        """Generate URL for a page"""
        if self.endpoint:
            args = dict(self.kwargs)
            args['page'] = page
            return url_for(self.endpoint, **args)
        return f"?page={page}"
    
    def iter_pages(self, left_edge=2, left_current=2, right_current=2, right_edge=2):
        """Iterates over the page numbers in the pagination.
        
        The four arguments control the thresholds how many numbers should be produced
        from the sides:
        
        left_edge: Number of pages to show from the beginning
        left_current: Number of pages to show before current page
        right_current: Number of pages to show after current page
        right_edge: Number of pages to show at the end
        
        Example:
        >>> pagination = Pagination(items, 5, 10, 'endpoint')
        >>> list(pagination.iter_pages())
        [1, 2, None, 3, 4, 5, 6, 7, None, 19, 20]
        """
        last = 0
        for num in range(1, self.pages + 1):
            # Show pages at left edge
            if num <= left_edge:
                yield num
                last = num
            # Show pages around current page
            elif (num > self.page - left_current - 1 and 
                  num < self.page + right_current + 1):
                yield num
                last = num
            # Show pages at right edge
            elif num > self.pages - right_edge:
                yield num
                last = num
            # Show gaps
            elif last and last + 1 < num:
                yield None
                last = None
