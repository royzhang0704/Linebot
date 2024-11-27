from rest_framework import serializers
from .models import Todolist

class TodoListSerializer(serializers.ModelSerializer):
    user_id = serializers.CharField(write_only=True)  # 用來接收 Line Bot 的 user_id，但不返回給客戶端

    class Meta:
        model = Todolist
        fields = ['title', 'user_id','status']  # 包含所有需要的欄位

    def create(self, validated_data):
        return Todolist.objects.create(**validated_data)
