# pages/api.py
"""
API-first messaging & notifications:

- GET  /api/messages/threads/               -> list threads (other user, unread count, last message)
- GET  /api/messages/thread/<username>/     -> list messages (supports before_id/after_id, limit)
- POST /api/messages/thread/<username>/     -> send message
- POST /api/block/<user_id>/toggle/         -> block/unblock
- GET  /api/notifications/summary/          -> unread count, favorited-by count, hot-date flags
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q, Max
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import MessageThread, Message, Favorite, Block, HotDate
from .serializers import ThreadSummarySerializer, MessageSerializer

User = get_user_model()

def _other_user(thread: MessageThread, me: User):
    return thread.user_b if thread.user_a_id == me.id else thread.user_a

def _blocked_either_way(u1: User, u2: User) -> bool:
    return (
        Block.objects.filter(blocker=u1, blocked=u2).exists()
        or Block.objects.filter(blocker=u2, blocked=u1).exists()
    )

def _get_or_create_thread(me: User, other: User) -> MessageThread:
    a, b = sorted([me.id, other.id])
    thread, _ = MessageThread.objects.get_or_create(user_a_id=a, user_b_id=b)
    return thread

class ThreadsListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        me = request.user
        threads = MessageThread.objects.filter(Q(user_a=me) | Q(user_b=me)).order_by("-updated_at")
        data = []
        for t in threads:
            other  = _other_user(t, me)
            unread = Message.objects.filter(thread=t, is_read=False).exclude(sender=me).count()
            last   = t.messages.order_by("-created_at").first()
            data.append({
                "other_username": other.username,
                "other_display": getattr(other, "first_name", "") or other.username,
                "updated_at": t.updated_at,
                "unread_count": unread,
                "last_message": (last.body[:120] if last else ""),
            })
        return Response(ThreadSummarySerializer(data, many=True).data)

class ThreadMessagesAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, username: str):
        me    = request.user
        other = get_object_or_404(User, username=username)
        if _blocked_either_way(me, other):
            return Response({"detail": "Messaging is blocked for this pair."}, status=403)
        a, b  = sorted([me.id, other.id])
        thread = get_object_or_404(MessageThread, user_a_id=a, user_b_id=b)

        limit    = int(request.GET.get("limit", 50))
        before_id = request.GET.get("before_id")
        after_id  = request.GET.get("after_id")

        qs = thread.messages.order_by("-id")
        if before_id: qs = qs.filter(id__lt=before_id)
        if after_id:  qs = qs.filter(id__gt=after_id)

        msgs = list(qs[:limit])
        if not after_id:
            msgs = list(reversed(msgs))  # chronological on initial load

        Message.objects.filter(thread=thread, is_read=False).exclude(sender=me).update(is_read=True)
        return Response(MessageSerializer(msgs, many=True).data)

    def post(self, request, username: str):
        me    = request.user
        other = get_object_or_404(User, username=username)
        if _blocked_either_way(me, other):
            return Response({"detail": "Messaging is blocked for this pair."}, status=403)

        thread = _get_or_create_thread(me, other)
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Empty message"}, status=400)
        msg = Message.objects.create(thread=thread, sender=me, body=body)
        thread.save(update_fields=["updated_at"])
        return Response(MessageSerializer(msg).data, status=201)

class BlockToggleAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, user_id: int):
        me    = request.user
        other = get_object_or_404(User, pk=user_id)
        if other == me:
            return Response({"detail": "Cannot block yourself"}, status=400)
        obj, created = Block.objects.get_or_create(blocker=me, blocked=other)
        if created:
            return Response({"status": "blocked"})
        obj.delete()
        return Response({"status": "unblocked"})

class NotificationsSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        me = request.user
        unread = (
            Message.objects
            .filter(thread__in=MessageThread.objects.filter(Q(user_a=me) | Q(user_b=me)), is_read=False)
            .exclude(sender=me)
            .count()
        )
        fav_by_others = Favorite.objects.filter(target=me).count()

        now = timezone.now()
        active_qs = HotDate.objects.filter(starts_at__lte=now, expires_at__gt=now)
        has_active = active_qs.exists()
        latest_active_ts = active_qs.aggregate(m=Max("updated_at"))["m"]

        profile = getattr(me, "profile", None)
        seen_ts = getattr(profile, "last_seen_hotdate_at", None)
        has_unseen = bool(latest_active_ts and (not seen_ts or latest_active_ts > seen_ts))

        return Response({
            "unread_messages": unread,
            "favorited_by_count": fav_by_others,
            "has_active_hot_date": has_active,
            "has_unseen_hot_date": has_unseen,
        })

