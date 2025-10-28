from .models import Category
from .models import Cart


def categories_context(request):
    return {
        "categories": Category.objects.all()
    }


def cart_item_count(request):
    count = 0
    if request.user.is_authenticated:
        count = Cart.objects.filter(user=request.user).count()
    return {'cart_item_count': count}
