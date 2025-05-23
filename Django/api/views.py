import boto3
import traceback
from django.shortcuts import get_object_or_404, render
from rest_framework import viewsets, generics
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from .models import MyUser, UserToken, Track, UserLikedTrack, Conversation, Message, Playlist, PlaylistTrack, UserFollowedPlaylist, Album, Artist, Genre, PremiumPayment, Genre
from .serializers import PlaylistSerializer, UserSerializer, SimpleTrackSerializer, AlbumSerializer, GenreSerializer, ArtistSerializer, PremiumPaymentSerializer, AlbumSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from django.utils import timezone
from .utils.s3_utils import generate_presigned_url
from django.http import Http404, JsonResponse
from .auth import CustomTokenAuthentication 
from rest_framework.decorators import authentication_classes
from rest_framework.decorators import permission_classes
from django.db.models import Q
import sys
import logging
from django.utils.timezone import datetime
from .models import Track, Album, Artist
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from time import time
from datetime import datetime
import json, hmac, hashlib, urllib.request, urllib.parse, random
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.contrib.auth.hashers import make_password
from google import genai
import os
import base64
from django.conf import settings
from django.core.files.base import ContentFile
import os
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import uuid
import os
import json
import hmac
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny    
from django.views.decorators.clickjacking import xframe_options_exempt
GEMINI_API_KEY = "AIzaSyCDBht1ZEgJStn-ycfpFGdWr599E6XC5WA"
client = genai.Client(api_key=GEMINI_API_KEY)

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Explain how AI works",
)

logger = logging.getLogger('django')

class TokenValidationView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        serializer = UserSerializer(user)
        response_data = serializer.data
        response_data['valid'] = True
        response_data.pop('password', None)
        return Response(response_data)
    
class UserViewSet(viewsets.ModelViewSet):
    queryset = MyUser.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == 'create':
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]
    
class LoginView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        user = authenticate(username=username, password=password)
        
        if user:
            UserToken.objects.filter(user=user).delete()
            token = UserToken.objects.create(
                user=user,
                expires=timezone.now() + timezone.timedelta(hours=24)
            )
            return Response({
                'token': token.key,
                'user_id': user.id,
                'username': user.username,
                'expires': token.expires,
                'role': getattr(user, 'role', 'user'),
                'avatarImg': user.avatarImg.url if user.avatarImg else None,
                'is_superuser': user.is_superuser
            })
        else:
            return Response({"error": "Thông tin đăng nhập không chính xác"}, status=status.HTTP_400_BAD_REQUEST)

class LoginWithGoogleView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        email = request.data.get('email')
        username = request.data.get('email')
        Img = request.data.get('photoURL')
        name = request.data.get('displayName', '')
        
        try:
            user = MyUser.objects.get(email=email)
            
            if Img and Img != user.avatarImg:
                user.avatarImg = Img
                user.save()
                
        except MyUser.DoesNotExist:
            name_parts = name.split(' ', 1)
            first_name = name_parts[0] if name_parts else ''
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            
            import uuid
            random_password = str(uuid.uuid4())
            
            user = MyUser.objects.create_user(
                username=username,
                email=email,
                password=random_password,
                first_name=first_name,
                last_name=last_name
            )
            
            if Img:
                user.avatarImg = Img
                user.save()
        
        UserToken.objects.filter(user=user).delete()
        token = UserToken.objects.create(
            user=user,
            expires=timezone.now() + timezone.timedelta(hours=24)
        )
        
        return Response({
            'token': token.key,
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'avatarImg': user.avatarImg.url if user.avatarImg else None,
            'role': getattr(user, 'role', 'user'),
            'expires': token.expires,
            'is_superuser': user.is_superuser
        })
class RandomTracksView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        tracks = Track.objects.select_related('album').prefetch_related('artists').order_by('?')[:6]
        track_ids = [track.id for track in tracks]
        context = {'request': request}
        
        if request.user and request.user.is_authenticated:
            liked_track_ids = UserLikedTrack.objects.filter(
                user=request.user, 
                track_id__in=track_ids
            ).values_list('track_id', flat=True)
            context['liked_track_ids'] = liked_track_ids
        serializer = SimpleTrackSerializer(tracks, many=True, context=context)
        return Response(serializer.data)
    
@method_decorator(xframe_options_exempt, name='dispatch')
class StreamAudioView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [AllowAny]
    
    def get(self, request, track_id):
        try:
            track = Track.objects.get(id=track_id)

            if track.is_premium:
                if not request.user or not request.user.is_authenticated:
                    return Response({
                        "error": "Yêu cầu đăng nhập để nghe bài hát premium."
                    }, status=status.HTTP_401_UNAUTHORIZED)
                
                # Kiểm tra xem người dùng có role 'premium'/'admin' HOẶC là superuser không
                allowed_roles = ['premium', 'admin']
                is_allowed_role = hasattr(request.user, 'role') and request.user.role in allowed_roles
                is_superuser = hasattr(request.user, 'is_superuser') and request.user.is_superuser
                
                if not (is_allowed_role or is_superuser):
                    return Response({
                        "error": "Bạn cần nâng cấp tài khoản Premium hoặc là Quản trị viên để nghe bài hát này."
                    }, status=status.HTTP_403_FORBIDDEN)

            s3_key = track.audio_file
            
            if '://' in s3_key:
                s3_key = s3_key.split('://', 1)[1]
                if '/' in s3_key:
                    s3_key = s3_key.split('/', 1)[1]

            logger.info(f"Attempting to generate presigned URL for S3 key: {s3_key}")
            presigned_url = generate_presigned_url(
                s3_key=s3_key,
                expiration=3600
            )
            
            if not presigned_url:
                return Response({"error": "Could not generate streaming URL"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Xác định file_type từ S3 key
            file_type = 'mp3' # Mặc định
            if track.audio_file and isinstance(track.audio_file, str):
                lower_uri = track.audio_file.lower()
                if lower_uri.endswith('.mp4'):
                    file_type = 'mp4'
                elif lower_uri.endswith('.mp3'):
                    file_type = 'mp3'
                    
            # --- Tạo presigned URL cho ảnh bìa track (nếu có) --- 
            track_cover_presigned_url = None
            if track.cover_image:
                try:
                    track_cover_presigned_url = generate_presigned_url(s3_key=track.cover_image, expiration=3600)
                except Exception as e:
                     logger.error(f"Error generating presigned URL for track cover {track.cover_image} in StreamAudioView: {e}")
                     # Không cần dừng, sẽ fallback về ảnh album hoặc null

            # --- Serialize artists --- 
            artists_data = ArtistSerializer(track.artists.all(), many=True).data

            return Response({
                "stream_url": presigned_url,
                "file_type": file_type, 
                "track_details": {
                    "id": track.id,
                    "title": track.title,
                    "artists": artists_data,
                    "album": track.album.title,
                    "duration_ms": track.duration_ms,
                    "track_cover_url": track_cover_presigned_url or (track.album.cover_image_url if hasattr(track.album, 'cover_image_url') else None)
                }
            })
            
        except Track.DoesNotExist:
            return Response({"error": "Track not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"Error in StreamAudioView: {str(e)}")
            print(traceback.format_exc())
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class TrackSearchView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        query = request.query_params.get('q', '')
        
        if not query:
            return Response({"error": "Search query is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        from django.db.models import Q
        tracks = Track.objects.filter(
            Q(title__icontains=query) |  
            Q(artists__name__icontains=query)  
        ).select_related('album').prefetch_related('artists').distinct()[:5]
        
        serializer = SimpleTrackSerializer(tracks, many=True)
        return Response(serializer.data)

class LikeTrackView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        user_id = request.data.get('user_id')
        track_id = request.data.get('track_id')
        
        if not user_id or not track_id:
            return Response({'error': 'Chưa điền đủ thông tin'}, 
                           status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = MyUser.objects.get(id=user_id)
            track = Track.objects.get(id=track_id)
            
            like_records = UserLikedTrack.objects.filter(user=user, track=track)
            
            if like_records.exists():
                like_records.delete()
                return Response({
                    'status': 'success',
                    'action': 'unlike',
                    'message': f"User {user.username} đã xóa yêu thích {track.title}"
                }, status=status.HTTP_200_OK)
            else:
                like = UserLikedTrack.objects.create(user=user, track=track)
                
                return Response({
                    'status': 'success',
                    'action': 'like',
                    'message': f"User {user.username} đã thích {track.title}",
                    'like_id': like.id
                }, status=status.HTTP_201_CREATED)
            
        except MyUser.DoesNotExist:
            return Response({'error': 'Không tìm thấy người dùng'}, status=status.HTTP_404_NOT_FOUND)
        except Track.DoesNotExist:
            return Response({'error': 'Không tìm thấy bài hát'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class CheckLikeStatusView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_id = request.query_params.get('user_id')
        track_id = request.query_params.get('track_id')
        
        if not user_id or not track_id:
            return Response({'error': 'Both user_id and track_id are required'}, 
                           status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = MyUser.objects.get(id=user_id)
            track = Track.objects.get(id=track_id)
            
            is_liked = UserLikedTrack.objects.filter(user=user, track=track).exists()
            
            return Response({
                'is_liked': is_liked
            }, status=status.HTTP_200_OK)
            
        except MyUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        except Track.DoesNotExist:
            return Response({'error': 'Track not found'}, status=status.HTTP_404_NOT_FOUND)
        
class LikedTracksView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            user = request.user
        else:
            try:
                user = MyUser.objects.get(id=user_id)
            except MyUser.DoesNotExist:
                return Response({'error': 'Ko co user nay'}, status=status.HTTP_404_NOT_FOUND)
        
        liked_tracks = Track.objects.filter(
            id__in=UserLikedTrack.objects.filter(user=user).values_list('track_id', flat=True)
        ).select_related('album').prefetch_related('artists')

        context = {
            'request': request,
            'liked_track_ids': [track.id for track in liked_tracks]
        }
        
        serializer = SimpleTrackSerializer(liked_tracks, many=True, context=context)
        return Response(serializer.data)       

class ConversationListView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    
    def get(self, request):
        user = request.user
        conversations = Conversation.objects.filter(participants=user)
        
        result = []
        for conv in conversations:
            other_user = conv.participants.exclude(id=user.id).first()
            if not other_user:
                continue
                
            last_message = conv.messages.order_by('-timestamp').first()
            if not last_message:
                continue
                
            unread_count = conv.messages.filter(is_read=False).exclude(sender=user).count()
    
            result.append({
                'id': conv.id,
                'username': other_user.username,
                'user_id': other_user.id,
                'lastMessage': last_message.content[:50],
                'timestamp': last_message.timestamp,
                'unread': unread_count
            })
            
        return Response(result)

class MessageListView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    
    def get(self, request, conversation_id):
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            if request.user not in conversation.participants.all():
                return Response({"error": "Không có quyền truy cập"}, status=403)
                
            messages = conversation.messages.order_by('timestamp')
            
            unread_messages = messages.filter(is_read=False).exclude(sender=request.user)
            for msg in unread_messages:
                msg.is_read = True
                msg.save()
                
            result = []
            for msg in messages:
                result.append({
                    'id': msg.id,
                    'sender': msg.sender.id,
                    'text': msg.content,
                    'timestamp': msg.timestamp.strftime('%H:%M'),
                    'is_read': msg.is_read
                })
                
            return Response(result)
        except Conversation.DoesNotExist:
            return Response({"error": "Không tìm thấy cuộc trò chuyện"}, status=404)
    
    def post(self, request, conversation_id):
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            
            if request.user not in conversation.participants.all():
                return Response({"error": "Không có quyền truy cập"}, status=403)
            
            content = request.data.get('content')
            if not content or not content.strip():
                return Response({"error": "Nội dung tin nhắn không được trống"}, status=400)
            
            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=content.strip(),
                is_read=False
            )
            
      
            return Response({
                'id': message.id,
                'sender': message.sender.id,
                'text': message.content,
                'timestamp': message.timestamp.strftime('%H:%M'),
                'is_read': message.is_read
            }, status=201)
            
        except Conversation.DoesNotExist:
            return Response({"error": "Không tìm thấy cuộc trò chuyện"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)
        
class UserSearchView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request):
        try:
            query = request.query_params.get('q', '')
            logger.info(f"Query: {query}")
            
            if len(query) < 2:
                logger.info("Query quá ngắn")
                return Response([])
            
            users = MyUser.objects.filter(username__icontains=query).exclude(id=request.user.id)[:10]
            
            logger.info(f"Tìm thấy {len(users)} kết quả")
            
            result = []
            for user in users:
                user_data = {
                    'id': user.id,
                    'username': user.username,
                    'avatarImg': user.avatarImg.url if user.avatarImg and hasattr(user.avatarImg, 'url') else None
                }
                result.append(user_data)
                
            # logger.info ("Kết quả:")
            return Response(result)
            
        except Exception as e:
            return Response({"error": str(e)}, status=500)
    
class ConversationCreateView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    
    def post(self, request):
        recipient_id = request.data.get('recipient_id')
        initial_message = request.data.get('initial_message')
        
        if not recipient_id:
            return Response({'error': 'Thiếu thông tin người nhận'}, status=400)
            
        try:
            recipient = MyUser.objects.get(id=recipient_id)
            existing_conversations = Conversation.objects.filter(participants=request.user).filter(participants=recipient)
            
            if existing_conversations.exists():
                conversation = existing_conversations.first()
            else:
                conversation = Conversation.objects.create()
                conversation.participants.add(request.user, recipient)
                conversation.save()
            
            # Create the initial message if provided
            message = None
            if initial_message and initial_message.strip():
                message = Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    content=initial_message,
                    is_read=False
                )
                
            return Response({
                'conversation_id': conversation.id,
                'recipient': {
                    'id': recipient.id,
                    'username': recipient.username,
                    'avatarImg': recipient.avatarImg.url if recipient.avatarImg else None
                },
                'message': {
                    'id': message.id,
                    'content': message.content,
                    'sender': message.sender.id,
                    'timestamp': message.timestamp.strftime('%H:%M')
                } if message else None
            })
        except MyUser.DoesNotExist:
            return Response({'error': 'Không tìm thấy người dùng'}, status=404)
 
class ConversationsSearchView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        conversations = Conversation.objects.filter(participants=user)
        result = []
        
        try:
            gemini_user = MyUser.objects.get(id=1)
            gemini_conversation = Conversation.objects.filter(
                participants=user
            ).filter(
                participants=gemini_user
            ).first()
            
            if not gemini_conversation:
                gemini_conversation = Conversation.objects.create()
                gemini_conversation.participants.add(user, gemini_user)
            
            last_message = Message.objects.filter(conversation=gemini_conversation).order_by('-timestamp').first()
            
            result.append({
                'conversation_id': gemini_conversation.id,
                'timestamp': last_message.timestamp if last_message else gemini_conversation.created_at,
                'last_message': last_message.content if last_message else "Xin chào! Tôi có thể giúp gì cho bạn?",
                'other_user': {
                    'id': gemini_user.id,
                    'username': gemini_user.username,
                    'avatarImg': gemini_user.avatarImg.url if gemini_user.avatarImg else None
                }
            })
            
        except MyUser.DoesNotExist:
            gemini_user = MyUser.objects.create(
                id=1,
                username="Gemini AI",
                email="gemini@example.com",
                password=make_password("geminiAI@2023"),
                is_active=True
            )
            gemini_conversation = Conversation.objects.create()
            gemini_conversation.participants.add(user, gemini_user)
            
            result.append({
                'conversation_id': gemini_conversation.id,
                'timestamp': gemini_conversation.created_at,
                'last_message': "Xin chào! Tôi có thể giúp gì cho bạn?",
                'other_user': {
                    'id': gemini_user.id,
                    'username': gemini_user.username,
                    'avatarImg': None
                }
            })
        
        for conversation in conversations:
            participants = conversation.participants.all()
            other_users = [p for p in participants if p.id != user.id and p.id != 1]
            if not other_users and participants.filter(id=1).exists():
                continue
                
            for other_user in other_users:
                last_message = Message.objects.filter(conversation=conversation).order_by('-timestamp').first()
                
                result.append({
                    'conversation_id': conversation.id,
                    'timestamp': last_message.timestamp if last_message else conversation.created_at,
                    'last_message': last_message.content if last_message else '',
                    'other_user': {
                        'id': other_user.id,
                        'username': other_user.username,
                        'avatarImg': other_user.avatarImg.url if other_user.avatarImg else None
                    }
                })
        
        return Response(result)
    
class ZaloPayView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get list of supported banks from ZaloPay"""
        try:
            config = {
                "app_id": 2553,  # Đã cập nhật
                "key1": "PcY4iZIKFCIdgZvA6ueMcMHHUbRLYjPL",  # Đã cập nhật
                "key2": "eG4r0GcoNtRGbO8",  # Đã cập nhật
                "endpoint": "https://sbgateway.zalopay.vn/api/getlistmerchantbanks"
            }
            
            reqtime = str(int(round(time() * 1000)))
            data_str = f"{config['app_id']}|{reqtime}"

            mac = hmac.new(
                config['key1'].encode(), 
                data_str.encode(), 
                hashlib.sha256
            ).hexdigest()

            request_data = {
                "appid": config["app_id"],
                "reqtime": reqtime,
                "mac": mac
            }

            response = urllib.request.urlopen(
                url=config["endpoint"], 
                data=urllib.parse.urlencode(request_data).encode()
            )
            
            result = json.loads(response.read())
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    def post(self, request):
        try:
            config = {
                "app_id": 2553,
                "key1": "PcY4iZIKFCIdgZvA6ueMcMHHUbRLYjPL",
                "key2": "eG4r0GcoNtRGbO8",
                "endpoint": "https://sb-openapi.zalopay.vn/v2/create"
            }
            
            amount = request.data.get('amount', 50000)
            bank_code = request.data.get('bank_code', '')
            payment_method = request.data.get('payment_method', '')  
            username = request.user.username

            current_time = int(round(time() * 1000))
            app_trans_id = "{:%y%m%d}_{}".format(datetime.today(), current_time)
            
            embed_data = {
                "redirecturl": "http://localhost:3000/payment-success"
            }
            
            if payment_method == 'vietqr':
                embed_data["preferred_payment_method"] = ["vietqr"]
                bank_code = ""  # Để trống cho VietQR
            elif payment_method == 'zalopay':
                embed_data["preferred_payment_method"] = ["zalopay_wallet"]
                bank_code = ""
            elif payment_method == 'credit_card':
                embed_data["preferred_payment_method"] = ["international_card"]
                bank_code = ""
            elif payment_method == 'atm':
                if bank_code:
                    # Nếu có mã ngân hàng cụ thể (VCB, ACB, v.v...), giữ nguyên mã và để preferred_method trống
                    embed_data["preferred_payment_method"] = []
                else:
                    # Nếu không có mã ngân hàng cụ thể, hiển thị tất cả ATM
                    embed_data["preferred_payment_method"] = ["domestic_card", "account"]
                    bank_code = ""
            else:
                embed_data["preferred_payment_method"] = []
                bank_code = ""
            
            print(f"Payment method: {payment_method}")
            print(f"Bank code: '{bank_code}'")
            print(f"Embed data before JSON: {embed_data}")
            
            # Chuẩn bị order
            order = {
                "app_id": config["app_id"],
                "app_user": username,
                "app_time": current_time,
                "amount": amount,
                "app_trans_id": app_trans_id,
                "bank_code": bank_code,
                "embed_data": json.dumps(embed_data),
                "item": "[]",
                "description": f"Spotify Premium - Thanh toán cho đơn hàng #{app_trans_id}"
            }
            
     
            print(f"Order sent to ZaloPay: {order}")
  
            data = "{}|{}|{}|{}|{}|{}|{}".format(
                order["app_id"], 
                order["app_trans_id"], 
                order["app_user"], 
                order["amount"], 
                order["app_time"], 
                order["embed_data"], 
                order["item"]
            )
            
            order["mac"] = hmac.new(config['key1'].encode(), data.encode(), hashlib.sha256).hexdigest()

            response = urllib.request.urlopen(
                url=config["endpoint"], 
                data=urllib.parse.urlencode(order).encode()
            )
            
            result = json.loads(response.read())
            print(f"ZaloPay response: {result}")
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"ZaloPay error: {str(e)}")
            print(traceback.format_exc())
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class VerifyPaymentView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [AllowAny]
    
    # Add this method to handle ZaloPay redirects
    @method_decorator(csrf_exempt)
    def get(self, request):
        """Handle ZaloPay redirect callback"""
        # Get payment data from query parameters
        payment_data = request.GET.dict()
        app_trans_id = payment_data.get('apptransid')
        status = payment_data.get('status')
        
        # Verify checksum
        config = {"key2": "eG4r0GcoNtRGbO8"}
        
        checksum_data = "{}|{}|{}|{}|{}|{}|{}".format(
            payment_data.get('appid', ''), 
            payment_data.get('apptransid', ''), 
            payment_data.get('pmcid', ''), 
            payment_data.get('bankcode', ''), 
            payment_data.get('amount', ''), 
            payment_data.get('discountamount', ''), 
            payment_data.get('status', '')
        )
        
        checksum = hmac.new(
            config['key2'].encode(), 
            checksum_data.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        # Build frontend redirect URL with all payment parameters
        frontend_url = "http://localhost:3000/payment-process"
        query_params = "&".join([f"{key}={value}" for key, value in payment_data.items()])
        
        # If checksum is valid, include a validation parameter
        if checksum == payment_data.get('checksum'):
            query_params += "&backend_verified=true"
        else:
            query_params += "&backend_verified=false"
            
        redirect_url = f"{frontend_url}?{query_params}"
        
        # Redirect to frontend
        return redirect(redirect_url)
    
    def post(self, request):
        # Existing post method remains the same
        # Get the payment data sent from frontend
        payment_data = request.data
        app_trans_id = payment_data.get('apptransid')
        status = payment_data.get('status')
        
        # Verify checksum
        config = {"key2": "uUfsWgfLkRLzq6W2uNXTCxrfxs51auny"}
        
        checksum_data = "{}|{}|{}|{}|{}|{}|{}".format(
            payment_data.get('appid'), 
            payment_data.get('apptransid'), 
            payment_data.get('pmcid'), 
            payment_data.get('bankcode'), 
            payment_data.get('amount'), 
            payment_data.get('discountamount'), 
            payment_data.get('status')
        )
        
        checksum = hmac.new(
            config['key2'].encode(), 
            checksum_data.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        if checksum != payment_data.get('checksum'):
            return Response({"error": "Invalid checksum"}, status=status.HTTP_400_BAD_REQUEST)
        
        if status == '1':  # payment successful
            # Update user to premium status
            user = request.user
            user.role = 'premium'
            user.save()
            
            return Response({
                "success": True,
                "message": "Payment verified and user upgraded to premium",
                "transaction_id": app_trans_id
            })
        else:
            return Response({
                "success": False,
                "message": "Payment failed",
                "status": status
            }, status=status.HTTP_400_BAD_REQUEST)
        
class UserProfileView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserSerializer(request.user)
        response_data = serializer.data
        response_data.pop('password', None)
        response_data['is_superuser'] = request.user.is_superuser 
        return Response(response_data)
    
class GeminiAIView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get conversation with Gemini AI"""
        try:
            user = request.user
            try:
                gemini_user = MyUser.objects.get(id=1)
            except MyUser.DoesNotExist:
                gemini_user = MyUser.objects.create(
                    id=1,
                    username="Gemini AI",
                    email="gemini@example.com",
                    password=make_password("geminiAI@2023"),  
                    is_active=True
                )
            
            conversation = Conversation.objects.filter(
                participants=user
            ).filter(
                participants=gemini_user
            ).first()
            
            if not conversation:
                conversation = Conversation.objects.create()
                conversation.participants.add(user, gemini_user)
                
                Message.objects.create(
                    conversation=conversation,
                    sender=gemini_user,
                    content="Xin chào! Tôi là Gemini AI, trợ lý ảo của bạn. Tôi có thể giúp gì cho bạn?",
                    is_read=False
                )
            
            messages = conversation.messages.order_by('timestamp')
            
            result = []
            for msg in messages:
                result.append({
                    'id': msg.id,
                    'sender': msg.sender.id,
                    'text': msg.content,
                    'timestamp': msg.timestamp.isoformat(),
                    'is_read': msg.is_read
                })
            
            return Response({
                'conversation_id': conversation.id,
                'messages': result
            })
            
        except Exception as e:
            logger.error(f"Error in GeminiAIView.get: {str(e)}")
            return Response({"error": str(e)}, status=500)
    
    def post(self, request):
        """Send message to Gemini AI with actual Gemini model response"""
        try:
            user = request.user
            message_text = request.data.get('message')
            
            if not message_text or not message_text.strip():
                return Response({"error": "Nội dung tin nhắn không được trống"}, status=400)
            
            # Get or create Gemini AI user
            try:
                gemini_user = MyUser.objects.get(id=1)
            except MyUser.DoesNotExist:
                gemini_user = MyUser.objects.create(
                    id=1,
                    username="Gemini AI",
                    email="gemini@example.com",
                    password=make_password("geminiAI@2023"),
                    is_active=True
                )
            
            # Get or create conversation
            conversation = Conversation.objects.filter(
                participants=user
            ).filter(
                participants=gemini_user
            ).first()
            
            if not conversation:
                conversation = Conversation.objects.create()
                conversation.participants.add(user, gemini_user)

            # Save user message
            user_message = Message.objects.create(
                conversation=conversation,
                sender=user,
                content=message_text.strip(),
                is_read=True  
            )
            
            # Get last few messages for context (max 5)
            recent_messages = conversation.messages.order_by('-timestamp')[:5][::-1]
            conversation_history = []
            
            for msg in recent_messages:
                role = "user" if msg.sender == user else "model"
                conversation_history.append(f"{role}: {msg.content}")
            
            # Prepare context with conversation history
            prompt = "\n".join(conversation_history)
            if not prompt:
                prompt = message_text.strip()
                
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",  # Using a more stable model
                    contents=f"{message_text}\n\nVui lòng trả lời bằng tiếng Việt."
                )
                
                ai_response = response.text
                if not ai_response or ai_response.strip() == "":
                    ai_response = "Xin lỗi, tôi không thể xử lý yêu cầu của bạn lúc này. Vui lòng thử lại sau."
                    
            except Exception as api_error:
                logger.error(f"Gemini API error: {str(api_error)}")
                ai_response = "Xin lỗi, đã xảy ra lỗi khi xử lý yêu cầu của bạn. Vui lòng thử lại sau."
            
            # Save AI response
            ai_message = Message.objects.create(
                conversation=conversation,
                sender=gemini_user,
                content=ai_response,
                is_read=False
            )
            
            return Response({
                'conversation_id': conversation.id,
                'user_message': {
                    'id': user_message.id,
                    'sender': user_message.sender.id,
                    'text': user_message.content,
                    'timestamp': user_message.timestamp.isoformat(),
                    'is_read': user_message.is_read
                },
                'ai_message': {
                    'id': ai_message.id,
                    'sender': ai_message.sender.id,
                    'text': ai_message.content,
                    'timestamp': ai_message.timestamp.isoformat(),
                    'is_read': ai_message.is_read
                }
            })
        except Exception as e:
           logger.error(f"Error in GeminiAIView.post: {str(e)}")
           return Response({"error": str(e)}, status=500)
        

class AdminUserListView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request):
        try:
            if request.user.role != 'admin':
                return Response({"error": "Không có quyền truy cập"}, status=status.HTTP_403_FORBIDDEN)
            
            users = MyUser.objects.all()
            
            result = []
            for user in users:
                user_data = {
                    'id': user.id,
                    'username': user.username,
                    'name': f"{user.first_name} {user.last_name}".strip(),
                    'email': user.email,
                    'image': user.avatarImg.url if user.avatarImg and hasattr(user.avatarImg, 'url') else None,
                    'status': 'Active' if user.is_active else 'Inactive',
                    'createdAt': user.date_joined.strftime('%Y-%m-%d'),
                    'role': user.role,
                    # Thêm số đơn hàng nếu có model liên quan
                    'orders': 0  # Cập nhật nếu có model Order
                }
                result.append(user_data)
                
            return Response(result)
            
        except Exception as e:
            return Response({"error": str(e)}, status=500)
        
from rest_framework.permissions import AllowAny

from rest_framework.permissions import AllowAny


from rest_framework.exceptions import AuthenticationFailed
class PublicUserListView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def get(self, request):
        users = MyUser.objects.all()
        
        result = []
        for user in users:
            avatarImg = user.avatarImg
            if avatarImg:
                if isinstance(avatarImg, str):
                    if avatarImg.startswith(('http://', 'https://')):
                        image_url = avatarImg  # Giữ nguyên URL bên ngoài
                    else:
                        image_url = request.build_absolute_uri(f'/media/{avatarImg}')
                else:
                    image_url = request.build_absolute_uri(avatarImg.url) if hasattr(avatarImg, 'url') else None
            else:
                image_url = None
                
            user_data = {
                'id': user.id,
                'username': user.username,
                'name': f"{user.first_name} {user.last_name}".strip() or user.username,
                'email': user.email,
                'image': image_url,
                'status': 'Active' if user.is_active else 'Inactive',
                'createdAt': user.date_joined.strftime('%Y-%m-%d'),
                'role': user.role,
                'is_superuser': user.is_superuser,  # Thêm dòng này
                'is_staff': user.is_staff,          # Thêm dòng này
            }
            result.append(user_data)
            
        return Response(result)


class BlockUser(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def post(self, request, user_id):
        try:
            user_id = int(user_id)
            user_to_block = MyUser.objects.get(id=user_id)
            
            user_to_block.is_active = False
            user_to_block.save()
            
            return Response({"message": f"Người dùng {user_to_block.username} đã bị chặn"}, status=200)
        except Exception as e:
            print(f"Error: {str(e)}")
            print(traceback.format_exc())
            return Response({"error": str(e)}, status=500)
        
class Unblock(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def post(self, request, user_id):
        try:
            user_id = int(user_id)
            user_to_unblock = MyUser.objects.get(id=user_id)
            
            user_to_unblock.is_active = True
            user_to_unblock.save()
            
            return Response({"message": f"Người dùng {user_to_unblock.username} đã được mở khóa"}, status=200)
        except Exception as e:
            print(f"Error: {str(e)}")
            print(traceback.format_exc())
            return Response({"error": str(e)}, status=500)
        
  
class CreateUserView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def post(self, request):
        try:
            username = request.data.get('username')
            email = request.data.get('email')
            password = request.data.get('password')
            first_name = request.data.get('first_name', '')
            last_name = request.data.get('last_name', '')
            is_superuser = request.data.get('is_superuser', False)
            is_staff = request.data.get('is_staff', False)
            is_active = request.data.get('is_active', True)
            avatarImg = request.data.get('avatarImg', None)
            role = request.data.get('role', 'user')
            
            if not username or not email or not password:
                return Response({
                    "detail": "Username, email và mật khẩu là bắt buộc"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user = MyUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_superuser=is_superuser,
                is_staff=is_staff,
                is_active=is_active,
                role=role
            )
            
            if avatarImg and avatarImg.startswith('data:image'):
                # Tạo thư mục lưu hình nếu chưa tồn tại
                
                UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'hinhanh')
                if not os.path.exists(UPLOAD_DIR):
                    os.makedirs(UPLOAD_DIR)
                
                format, imgstr = avatarImg.split(';base64,')
                ext = format.split('/')[-1]
                filename = f"{username}_{user.id}.{ext}"
                
                data = ContentFile(base64.b64decode(imgstr))
                file_path = os.path.join(UPLOAD_DIR, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(data.read())
                
                user.avatarImg = f"hinhanh/{filename}"
                user.save()
                
            return Response({
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "message": "Người dùng đã được tạo thành công"
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            print(f"Error creating user: {str(e)}")
            print(traceback.format_exc())
            return Response({
                "detail": f"Lỗi khi tạo người dùng: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UpdateUserView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def put(self, request, user_id):
        try:
            user = MyUser.objects.get(id=user_id)
            
            username = request.data.get('username')
            email = request.data.get('email')
            password = request.data.get('password', None)
            first_name = request.data.get('first_name', '')
            last_name = request.data.get('last_name', '')
            is_superuser = request.data.get('is_superuser', user.is_superuser)
            is_staff = request.data.get('is_staff', user.is_staff)
            is_active = request.data.get('is_active', user.is_active)
            avatarImg = request.data.get('avatarImg', user.avatarImg)
            role = request.data.get('role', user.role)
            if not username or not email:
                return Response({
                    "detail": "Username và email là bắt buộc"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if username != user.username and MyUser.objects.filter(username=username).exists():
                return Response({
                    "detail": "Tên đăng nhập đã tồn tại"
                }, status=status.HTTP_400_BAD_REQUEST)
                
            if email != user.email and MyUser.objects.filter(email=email).exists():
                return Response({
                    "detail": "Email đã tồn tại"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user.username = username
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_superuser = is_superuser
            user.is_staff = is_staff
            user.is_active = is_active
            user.role = role
            
            if password:
                user.set_password(password)
            
            if avatarImg and avatarImg != user.avatarImg and avatarImg.startswith('data:image'):
            
                
                UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'hinhanh')
                if not os.path.exists(UPLOAD_DIR):
                    os.makedirs(UPLOAD_DIR)
                
                format, imgstr = avatarImg.split(';base64,')
                ext = format.split('/')[-1]
                filename = f"{username}_{user.id}.{ext}"
                
                data = ContentFile(base64.b64decode(imgstr))
                file_path = os.path.join(UPLOAD_DIR, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(data.read())
                
                user.avatarImg = f"hinhanh/{filename}"
            
            user.save()
                
            return Response({
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "role": user.role,
                "message": "Cập nhật người dùng thành công"
            }, status=status.HTTP_200_OK)
            
        except MyUser.DoesNotExist:
            return Response({
                "detail": f"Không tìm thấy người dùng với ID {user_id}"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"Error updating user: {str(e)}")
            print(traceback.format_exc())
            return Response({
                "detail": f"Lỗi khi cập nhật người dùng: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class TrackListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            tracks = Track.objects.all().select_related('album').prefetch_related('artists')
            
            # <<< Sử dụng SimpleTrackSerializer >>>
            context = {'request': request} # Cần context nếu user đăng nhập để check like
            if request.user and request.user.is_authenticated:
                liked_track_ids = UserLikedTrack.objects.filter(
                    user=request.user, 
                    track_id__in=[t.id for t in tracks]
                ).values_list('track_id', flat=True)
                context['liked_track_ids'] = liked_track_ids
                
            serializer = SimpleTrackSerializer(tracks, many=True, context=context)
            return Response(serializer.data)

        except Exception as e:
            print(f"Error fetching tracks: {str(e)}")
            print(traceback.format_exc())
            return Response({
                "detail": f"Lỗi khi lấy danh sách tracks: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AddTrackView(APIView):
    permission_classes = [AllowAny]  
    
    def post(self, request):
        try:
            # --- Lấy dữ liệu và files --- 
            title = request.data.get('title')
            album_id = request.data.get('album')
            duration_ms = request.data.get('duration_ms')
            genre_ids = request.data.getlist('genres') 
            artist_ids = request.data.getlist('artists') or [1] 
            
            audio_file = request.FILES.get('audio_file')
            cover_image = request.FILES.get('cover_image') 
            
            track_number = request.data.get('track_number', 1) 
            disc_number = request.data.get('disc_number', 1)
            explicit = request.data.get('explicit', False)
            popularity = request.data.get('popularity', 50)
            is_premium = request.data.get('is_premium', False)

            # --- Validation dữ liệu cơ bản --- 
            if not title or not album_id or not audio_file or not duration_ms:
                return Response({"detail": "Tên, album, file nhạc và thời lượng là bắt buộc."}, status=status.HTTP_400_BAD_REQUEST)
            
            # --- Lấy Album TRƯỚC khi xử lý S3 --- 
            try:
                album = Album.objects.get(id=album_id)
            except Album.DoesNotExist:
                logger.warning(f"Thêm track thất bại: Không tìm thấy album ID {album_id}")
                return Response({"detail": f"Không tìm thấy album với ID {album_id}"}, status=status.HTTP_404_NOT_FOUND)
            except ValueError:
                 logger.warning(f"Thêm track thất bại: ID Album không hợp lệ {album_id}")
                 return Response({"detail": "ID Album không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)
            
            # --- Validation loại tệp --- 
            allowed_audio_types = ['audio/mpeg', 'video/mp4'] # MP3, MP4
            if audio_file.content_type not in allowed_audio_types:
                return Response({"detail": f"Loại file nhạc không hợp lệ. Chỉ chấp nhận MP3, MP4. (Nhận được: {audio_file.content_type})"}, status=status.HTTP_400_BAD_REQUEST)

            if cover_image:
                allowed_image_types = ['image/jpeg', 'image/png'] # JPG, PNG
                if cover_image.content_type not in allowed_image_types:
                    return Response({"detail": f"Loại file ảnh bìa không hợp lệ. Chỉ chấp nhận JPG, PNG. (Nhận được: {cover_image.content_type})"}, status=status.HTTP_400_BAD_REQUEST)
            
            # --- Khởi tạo Boto3 S3 client --- 
            try:
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_S3_REGION_NAME 
                )
                bucket_name = settings.AWS_STORAGE_BUCKET_NAME
            except AttributeError as e:
                 logger.error(f"Thiếu cài đặt AWS trong settings: {e}")
                 return Response({"detail": "Lỗi cấu hình máy chủ (AWS)."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # --- Xử lý Upload Audio File lên S3 --- 
            audio_extension = 'mp4' if audio_file.content_type == 'video/mp4' else 'mp3'
            audio_s3_key = f"tracks/{uuid.uuid4()}.{audio_extension}"
            try:
                logger.info(f"Đang upload audio lên S3: Key={audio_s3_key}, Bucket={bucket_name}") # <<< Thêm log
                s3_client.upload_fileobj(
                    audio_file, 
                    bucket_name,
                    audio_s3_key,
                    ExtraArgs={'ContentType': audio_file.content_type} 
                )
                logger.info(f"Upload audio thành công: Key={audio_s3_key}") # <<< Thêm log
            except Exception as e:
                logger.error(f"Lỗi upload audio lên S3: {e}")
                logger.error(traceback.format_exc()) # <<< Log full traceback
                return Response({"detail": "Lỗi upload file nhạc lên server."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # --- Xử lý Upload Cover Image lên S3 (nếu có) --- 
            cover_s3_key = None
            if cover_image:
                image_extension = 'png' if cover_image.content_type == 'image/png' else 'jpg'
                cover_s3_key = f"track_covers/{uuid.uuid4()}.{image_extension}"
                try:
                    logger.info(f"Đang upload ảnh bìa lên S3: Key={cover_s3_key}, Bucket={bucket_name}") # <<< Thêm log
                    s3_client.upload_fileobj(
                        cover_image,
                        bucket_name,
                        cover_s3_key,
                        ExtraArgs={'ContentType': cover_image.content_type}
                    )
                    logger.info(f"Upload ảnh bìa thành công: Key={cover_s3_key}") # <<< Thêm log
                except Exception as e:
                    logger.error(f"Lỗi upload ảnh bìa lên S3: {e}")
                    logger.error(traceback.format_exc()) # <<< Log full traceback
                    cover_s3_key = None 

            # --- Tạo và lưu đối tượng Track với S3 Keys --- 
            track = Track(
                title=title,
                album=album,
                duration_ms=int(duration_ms) if duration_ms else 0,
                audio_file=audio_s3_key,     # <<< Sửa từ uri sang audio_file
                cover_image=cover_s3_key,    
                track_number=track_number,
                disc_number=disc_number,
                explicit=explicit,
                popularity=popularity,
                is_premium=is_premium
            )
            track.save() 

            # --- Gán Artists và Genres --- 
            try:
                valid_artist_ids = [int(aid) for aid in artist_ids]
                artists = Artist.objects.filter(id__in=valid_artist_ids)
                track.artists.set(artists)
            except (ValueError, TypeError):
                 print(f"Lỗi khi xử lý artist IDs: {artist_ids}") # Log lỗi
            except Artist.DoesNotExist:
                 print(f"Một số artist ID không tồn tại: {artist_ids}") # Log lỗi

            if genre_ids:
                try:
                    valid_genre_ids = [int(gid) for gid in genre_ids]
                    genres = Genre.objects.filter(id__in=valid_genre_ids)
                    track.genres.set(genres)
                except (ValueError, TypeError) as e:
                    print(f"Lỗi khi xử lý genre IDs: {e}")
                except Genre.DoesNotExist:
                    print(f"Một số genre ID không tồn tại: {genre_ids}")

            # --- Chuẩn bị và trả về Response --- 
            response_data = {
                "id": track.id,
                "title": track.title,
                "album": track.album.title,
                "audio_file_key": track.audio_file, 
                "cover_image_key": track.cover_image, 
                "duration_ms": track.duration_ms,
                "message": "Bài hát đã được thêm thành công lên S3"
            }
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            print(f"Lỗi không xác định khi thêm track: {str(e)}")
            print(traceback.format_exc())
            return Response({
                "detail": f"Lỗi máy chủ nội bộ khi thêm bài hát."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




def format_playlist_data(playlist):
    return {
        'id': playlist.id,
        'name': playlist.name,
        'description': playlist.description,
        'cover_image_url': playlist.cover_image_url,
        'track_count': playlist.tracks.count(),
        'creator': playlist.creator.id,
        'creator_username': playlist.creator.username,
        'is_public': playlist.is_public,
        'followers_count': playlist.followers_count,
        'created_at': playlist.created_at
    }

def handle_cover_image(request, playlist):
    if 'cover_image' in request.FILES:
        cover_image = request.FILES['cover_image']
        file_name = f"playlist_covers/{str(uuid.uuid4())}{cover_image.name}"
        file_path = default_storage.save(file_name, cover_image)
        playlist.cover_image_url = default_storage.url(file_path)
        playlist.save()

class PlaylistView(APIView):
    authentication_classes = [CustomTokenAuthentication] 
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        name = request.data.get('name', 'New Playlist')
        description = request.data.get('description', '')
        track_ids = request.data.getlist('tracks', [])
        
        playlist = Playlist.objects.create(
            name=name,
            description=description,
            creator=request.user,
            is_public=True
        )
        
        handle_cover_image(request, playlist)
        
        for i, track_id in enumerate(track_ids):
            try:
                track = Track.objects.get(id=track_id)
                PlaylistTrack.objects.create(
                    playlist=playlist,
                    track=track,
                    position=i,
                    added_by=request.user
                )
            except:
                pass
                
        UserFollowedPlaylist.objects.create(
            user=request.user,
            playlist=playlist
        )
        playlist.followers_count = 1
        playlist.save()
        
        return Response(format_playlist_data(playlist), status=status.HTTP_201_CREATED)
    
    def get(self, request):
        playlists = Playlist.objects.filter(creator=request.user)
        return Response([format_playlist_data(p) for p in playlists])


class PlaylistFollowView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        playlist_id = request.data.get('playlist_id')
        if not playlist_id:
            return Response({'error': 'Missing playlist ID'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            playlist = Playlist.objects.get(id=playlist_id)
            follow_record = UserFollowedPlaylist.objects.filter(user=request.user, playlist=playlist)
            
            if follow_record.exists():
                follow_record.delete()
                playlist.followers_count = max(0, playlist.followers_count - 1)
                playlist.save()
                return Response({'action': 'unfollow'})
            else:
                UserFollowedPlaylist.objects.create(user=request.user, playlist=playlist)
                playlist.followers_count += 1
                playlist.save()
                return Response({'action': 'follow'})
                
        except:
            return Response({'error': 'Error processing request'}, status=status.HTTP_400_BAD_REQUEST)
            
    def get(self, request):
        playlist_id = request.query_params.get('playlist_id')
        if not playlist_id:
            return Response({'error': 'Missing playlist ID'}, status=status.HTTP_400_BAD_REQUEST)
            
        is_following = UserFollowedPlaylist.objects.filter(
            user=request.user, 
            playlist_id=playlist_id
        ).exists()
        return Response({'is_following': is_following})


class FollowedPlaylistsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        followed_playlist_ids = UserFollowedPlaylist.objects.filter(
            user=request.user
        ).values_list('playlist_id', flat=True)
        
        playlists = Playlist.objects.filter(id__in=followed_playlist_ids)
        
        result = []
        for playlist in playlists:
            data = format_playlist_data(playlist)
            data['creator'] = {
                'id': playlist.creator.id,
                'username': playlist.creator.username
            }
            result.append(data)
            
        return Response(result)


class PlaylistDetailView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get_playlist(self, request, playlist_id, creator_only=False):
        try:
            if creator_only:
                return Playlist.objects.get(id=playlist_id, creator=request.user)
            
            user_playlists = Playlist.objects.filter(
                Q(creator=request.user) | 
                Q(id__in=UserFollowedPlaylist.objects.filter(user=request.user).values_list('playlist_id', flat=True))
            )
            return user_playlists.get(id=playlist_id)
        except:
            return None
    
    def get(self, request, playlist_id):
        playlist = self.get_playlist(request, playlist_id)
        if not playlist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
            
        result = format_playlist_data(playlist)
        result['tracks'] = []
        
        playlist_tracks = PlaylistTrack.objects.filter(playlist=playlist).order_by('position')
        for pt in playlist_tracks:
            track = pt.track
            result['tracks'].append({
                'position': pt.position,
                'added_at': pt.added_at,
                'added_by': pt.added_by.username if pt.added_by else None,
                'track': {
                    'id': track.id,
                    'title': track.title,
                    'duration_ms': track.duration_ms,
                    'artists': [{'id': artist.id, 'name': artist.name} for artist in track.artists.all()],
                    'album': {
                        'id': track.album.id if track.album else None,
                        'title': track.album.title if track.album else "Unknown Album",
                        'cover_image_url': track.album.cover_image_url if track.album else None
                    }
                }
            })
            
        return Response(result)

    def put(self, request, playlist_id):
        playlist = self.get_playlist(request, playlist_id, creator_only=True)
        if not playlist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
                           
        if 'name' in request.data:
            playlist.name = request.data['name']
        if 'description' in request.data:
            playlist.description = request.data['description']
            
        handle_cover_image(request, playlist)
        playlist.save()
        
        return Response(format_playlist_data(playlist))
        
    def post(self, request, playlist_id):
        playlist = self.get_playlist(request, playlist_id, creator_only=True)
        if not playlist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
                           
        track_id = request.data.get('track_id')
        position = request.data.get('position', 0)
        
        if not track_id:
            return Response({'error': 'Track ID required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            track = Track.objects.get(id=track_id)
            if PlaylistTrack.objects.filter(playlist=playlist, track=track).exists():
                return Response({'error': 'Track already in playlist'}, status=status.HTTP_400_BAD_REQUEST)
                               
            PlaylistTrack.objects.create(
                playlist=playlist,
                track=track,
                position=position,
                added_by=request.user
            )
            return Response({'success': True})
            
        except:
            return Response({'error': 'Track not found'}, status=status.HTTP_404_NOT_FOUND)
       
    def delete(self, request, playlist_id):
        playlist = self.get_playlist(request, playlist_id, creator_only=True)
        if not playlist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
            
        playlist.delete()
        return Response({'success': True})
            
    def remove_track(self, request, playlist_id):
        playlist = self.get_playlist(request, playlist_id, creator_only=True)
        if not playlist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        
        data = json.loads(request.body)
        track_id = data.get('track_id')
        if not track_id:
            return Response(
                {'error': 'Track ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            playlist_track = PlaylistTrack.objects.get(playlist=playlist, track_id=track_id)
            playlist_track.delete()
            
            remaining_tracks = PlaylistTrack.objects.filter(playlist=playlist).order_by('position')
            for i, pt in enumerate(remaining_tracks):
                pt.position = i
                pt.save()
            
            return Response({
                'success': True, 
                'message': 'Track removed from playlist'
            })
            
        except PlaylistTrack.DoesNotExist:
            return Response(
                {'error': 'Track not found in this playlist'}, 
                status=status.HTTP_404_NOT_FOUND
            )
                
        
class CheckLikeStatusView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_id = request.query_params.get('user_id')
        track_id = request.query_params.get('track_id')
        
        if not user_id or not track_id:
            return Response({'error': 'Missing user_id or track_id'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = MyUser.objects.get(id=user_id)
            is_liked = UserLikedTrack.objects.filter(user=user, track_id=track_id).exists()
            return Response({'is_liked': is_liked})
        except:
            return Response({'error': 'Error checking like status'}, status=status.HTTP_400_BAD_REQUEST)
        
# Add this new view class:

class PlaylistRemoveTrackView(APIView):
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, playlist_id):
        try:
            try:
                playlist = Playlist.objects.get(id=playlist_id)
                
                if playlist.creator != request.user:
                    return Response(
                        {'error': 'You do not have permission to modify this playlist'}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
            except Playlist.DoesNotExist:
                return Response(
                    {'error': 'Playlist not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            data = json.loads(request.body)
            track_id = data.get('track_id')
            
            if not track_id:
                return Response(
                    {'error': 'Track ID is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                playlist_track = PlaylistTrack.objects.get(playlist=playlist, track_id=track_id)
                playlist_track.delete()
                
                remaining_tracks = PlaylistTrack.objects.filter(playlist=playlist).order_by('position')
                for i, pt in enumerate(remaining_tracks):
                    pt.position = i
                    pt.save()
                
                return Response({
                    'success': True, 
                    'message': 'Track removed from playlist'
                })
                
            except PlaylistTrack.DoesNotExist:
                return Response(
                    {'error': 'Track not found in this playlist'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# Recommended Tracks View
import random # Make sure random is imported

class RecommendedTracksView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            # Lấy tất cả tracks, sắp xếp ngẫu nhiên
            tracks_qs = Track.objects.select_related('album').prefetch_related('artists').order_by('?')

            # Xác định số lượng bài hát cần lấy (tối đa 10)
            total_tracks = tracks_qs.count()
            limit = min(total_tracks, 10) # Lấy tối đa 10 bài, hoặc ít hơn nếu không đủ

            # Lấy số lượng bài hát đã xác định
            recommended_tracks = tracks_qs[:limit]

            # Chuẩn bị context cho serializer (để kiểm tra like status nếu user đăng nhập)
            context = {'request': request}
            if request.user and request.user.is_authenticated:
                liked_track_ids = UserLikedTrack.objects.filter(
                    user=request.user,
                    track_id__in=[t.id for t in recommended_tracks]
                ).values_list('track_id', flat=True)
                context['liked_track_ids'] = liked_track_ids

            # Serialize dữ liệu
            serializer = SimpleTrackSerializer(recommended_tracks, many=True, context=context)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in RecommendedTracksView: {str(e)}") 
            # import traceback
            # logger.error(traceback.format_exc())
            return Response({"error": "Could not fetch recommended tracks"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Public Playlists View
class PublicPlaylistsView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            # Lấy các playlist công khai, sắp xếp ngẫu nhiên
            playlists_qs = Playlist.objects.filter(is_public=True).order_by('?')

            # Xác định số lượng playlist cần lấy (tối đa 10)
            total_playlists = playlists_qs.count()
            limit = min(total_playlists, 10) # Lấy tối đa 10 playlist, hoặc ít hơn nếu không đủ

            # Lấy số lượng playlist đã xác định
            public_playlists = playlists_qs[:limit]

            # Sử dụng lại hàm format_playlist_data để định dạng kết quả
            # Cần đảm bảo hàm này có sẵn hoặc import nếu cần
            # Giả sử format_playlist_data đã được định nghĩa trong file này
            serializer = [format_playlist_data(p) for p in public_playlists]

            return Response(serializer)

        except Exception as e:
            logger.error(f"Error in PublicPlaylistsView: {str(e)}")
            # import traceback
            # logger.error(traceback.format_exc())
            return Response({"error": "Could not fetch public playlists"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)