import datetime
import time
from django.http import HttpResponse 
from django.utils.deprecation import MiddlewareMixin    #Helper class for writing middleware that is compatible with both old-style and new-style middleware.


class RequestLoggingMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        super().__init__(get_response)

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        end_time = time.time()
        time_taken = (end_time - start_time) * 1000  # in milliseconds
        print(f"{request.method} {request.path} {response.status_code} {time_taken:.2f}ms")
        return response
