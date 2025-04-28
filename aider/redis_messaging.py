import json
import time
from typing import Optional, List, Dict, Any

import redis


class RedisMessaging:
    """
    Handles Redis-based messaging between agents.
    
    This class provides methods to send and receive messages using Redis pub/sub
    and list data structures, allowing for both real-time communication and
    message queuing between different aider instances.
    """
    
    def __init__(
        self, 
        redis_url: str = "redis://localhost:6379/0",
        channel_prefix: str = "aider:",
        agent_id: Optional[str] = None,
        verbose: bool = False
    ):
        """
        Initialize the Redis messaging system.
        
        Args:
            redis_url: Redis connection string
            channel_prefix: Prefix for Redis channels and keys
            agent_id: Unique identifier for this agent
            verbose: Whether to print debug information
        """
        self.redis_url = redis_url
        self.channel_prefix = channel_prefix
        self.agent_id = agent_id or f"agent:{time.time()}"
        self.verbose = verbose
        
        # Connect to Redis
        try:
            self.redis = redis.from_url(redis_url)
            self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
            if self.verbose:
                print(f"Connected to Redis at {redis_url}")
        except redis.exceptions.ConnectionError as e:
            print(f"Error connecting to Redis: {e}")
            self.redis = None
            self.pubsub = None
    
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        if not self.redis:
            return False
        try:
            return self.redis.ping()
        except:
            return False
    
    def get_input_channel(self) -> str:
        """Get the channel name for receiving input."""
        return f"{self.channel_prefix}input:{self.agent_id}"
    
    def get_output_channel(self) -> str:
        """Get the channel name for sending output."""
        return f"{self.channel_prefix}output:{self.agent_id}"
    
    def get_broadcast_channel(self) -> str:
        """Get the channel name for broadcast messages."""
        return f"{self.channel_prefix}broadcast"
    
    def subscribe(self, channel: str) -> None:
        """Subscribe to a Redis channel."""
        if not self.is_connected():
            return
        self.pubsub.subscribe(channel)
        if self.verbose:
            print(f"Subscribed to channel: {channel}")
    
    def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a Redis channel."""
        if not self.is_connected():
            return
        self.pubsub.unsubscribe(channel)
        if self.verbose:
            print(f"Unsubscribed from channel: {channel}")
    
    def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """Publish a message to a Redis channel."""
        if not self.is_connected():
            return
        self.redis.publish(channel, json.dumps(message))
        if self.verbose:
            print(f"Published to {channel}: {message}")
    
    def get_message(self, timeout: float = 0.01) -> Optional[Dict[str, Any]]:
        """
        Get a message from subscribed channels.
        
        Args:
            timeout: Time to wait for a message in seconds
            
        Returns:
            Message dict or None if no message available
        """
        if not self.is_connected():
            return None
            
        message = self.pubsub.get_message(timeout=timeout)
        if message and message.get('type') == 'message':
            try:
                return json.loads(message['data'])
            except json.JSONDecodeError:
                if self.verbose:
                    print(f"Error decoding message: {message['data']}")
                return {'type': 'raw', 'content': message['data']}
        return None
    
    def push_message(self, queue_name: str, message: Dict[str, Any]) -> None:
        """Push a message to a Redis list."""
        if not self.is_connected():
            return
        self.redis.rpush(queue_name, json.dumps(message))
        if self.verbose:
            print(f"Pushed to {queue_name}: {message}")
    
    def pop_message(self, queue_name: str, timeout: int = 0) -> Optional[Dict[str, Any]]:
        """
        Pop a message from a Redis list.
        
        Args:
            queue_name: Name of the Redis list
            timeout: Time to wait for a message in seconds (0 = no wait)
            
        Returns:
            Message dict or None if no message available
        """
        if not self.is_connected():
            return None
            
        if timeout > 0:
            # Use blocking pop with timeout
            result = self.redis.blpop(queue_name, timeout=timeout)
            if result:
                _, data = result
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    if self.verbose:
                        print(f"Error decoding message: {data}")
                    return {'type': 'raw', 'content': data}
        else:
            # Use non-blocking pop
            data = self.redis.lpop(queue_name)
            if data:
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    if self.verbose:
                        print(f"Error decoding message: {data}")
                    return {'type': 'raw', 'content': data}
        
        return None
    
    def get_input_queue(self) -> str:
        """Get the queue name for receiving input."""
        return f"{self.channel_prefix}input_queue:{self.agent_id}"
    
    def get_output_queue(self) -> str:
        """Get the queue name for sending output."""
        return f"{self.channel_prefix}output_queue:{self.agent_id}"
    
    def send_user_input(self, content: str, target_agent: Optional[str] = None) -> None:
        """
        Send user input to another agent or broadcast.
        
        Args:
            content: The message content
            target_agent: Target agent ID or None for broadcast
        """
        message = {
            'type': 'user_input',
            'content': content,
            'from_agent': self.agent_id,
            'timestamp': time.time()
        }
        
        if target_agent:
            # Send to specific agent's input queue
            queue_name = f"{self.channel_prefix}input_queue:{target_agent}"
            self.push_message(queue_name, message)
        else:
            # Broadcast to all agents
            self.publish(self.get_broadcast_channel(), message)
    
    def send_ai_output(self, content: str, target_agent: Optional[str] = None) -> None:
        """
        Send AI output to another agent or broadcast.
        
        Args:
            content: The message content
            target_agent: Target agent ID or None for broadcast
        """
        message = {
            'type': 'ai_output',
            'content': content,
            'from_agent': self.agent_id,
            'timestamp': time.time()
        }
        
        if target_agent:
            # Send to specific agent's output queue
            queue_name = f"{self.channel_prefix}output_queue:{target_agent}"
            self.push_message(queue_name, message)
        else:
            # Broadcast to all agents
            self.publish(self.get_broadcast_channel(), message)
    
    def send_tool_output(self, content: str, target_agent: Optional[str] = None) -> None:
        """
        Send tool output to another agent or broadcast.
        
        Args:
            content: The message content
            target_agent: Target agent ID or None for broadcast
        """
        message = {
            'type': 'tool_output',
            'content': content,
            'from_agent': self.agent_id,
            'timestamp': time.time()
        }
        
        if target_agent:
            # Send to specific agent's output queue
            queue_name = f"{self.channel_prefix}output_queue:{target_agent}"
            self.push_message(queue_name, message)
        else:
            # Broadcast to all agents
            self.publish(self.get_broadcast_channel(), message)
    
    def get_available_agents(self) -> List[str]:
        """
        Get a list of available agent IDs.
        
        Returns:
            List of agent IDs
        """
        if not self.is_connected():
            return []
            
        pattern = f"{self.channel_prefix}input_queue:*"
        keys = self.redis.keys(pattern)
        return [key.decode('utf-8').split(':')[-1] for key in keys]
    
    def cleanup(self) -> None:
        """Clean up Redis connections."""
        if self.pubsub:
            self.pubsub.close()
        # Don't close the Redis connection as it might be shared
