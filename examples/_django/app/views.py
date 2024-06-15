from django.http.response import JsonResponse


def hello(request):
    return JsonResponse({"msg": "Hello world"})
