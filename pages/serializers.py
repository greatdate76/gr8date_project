# pages/serializers.py
from rest_framework import serializers
from .models import Message

class ThreadSummarySerializer(serializers.Serializer):
    other_username = serializers.CharField()
    other_display   = serializers.CharField()
    updated_at      = serializers.DateTimeField()
    unread_count    = serializers.IntegerField()
    last_message    = serializers.CharField(allow_blank=True)

class MessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.SerializerMethodField()

    class Meta:
        model  = Message
        fields = ["id", "sender_username", "body", "is_read", "created_at"]

    def get_sender_username(self, obj):
        return getattr(obj.sender, "username", "")

