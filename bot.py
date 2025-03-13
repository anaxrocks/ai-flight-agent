import os
import discord
import logging
import json
import requests

from discord.ext import commands
from discord.ext import tasks
import datetime
from dotenv import load_dotenv
from agent import MistralAgent

PREFIX = "!"

# Setup logging
logger = logging.getLogger("discord")

# Load the environment variables
load_dotenv()

# Create the bot with all intents
# The message content and members intent must be enabled in the Discord Developer Portal for the bot to work.
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Import the Mistral agent from the agent.py file
agent = MistralAgent()

# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")

# Refresh session if too much time has passed
@tasks.loop(minutes=5)
async def check_sessions_timeout():
    """Check all user sessions and end those that have timed out."""
    if not hasattr(agent, 'user_sessions'):
        return
    
    current_time = datetime.datetime.now(datetime.timezone.utc)
    timeout_seconds = 600  # 10 minutes
    
    for user_id, session in list(agent.user_sessions.items()):
        if session.get('active', False):
            last_time = session.get('last_interaction')
            
            if isinstance(last_time, str):
                last_time = datetime.datetime.fromisoformat(last_time).replace(tzinfo=datetime.timezone.utc)
            elif last_time and last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=datetime.timezone.utc)
            
            if last_time:
                time_diff = (current_time - last_time).total_seconds()
                
                # If more than 10 minutes have passed, end the session
                if time_diff > timeout_seconds:
                    agent.user_sessions[user_id]['active'] = False
                    logger.info(f"Periodic check: Session timed out for user {user_id} after {time_diff} seconds of inactivity")

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.
    """
    logger.info(f"{bot.user} has connected to Discord!")
    
    # Set the bot's status to indicate it's a travel assistant
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, 
        name="flight requests"
    ))

    # Start the session timeout check task
    if not check_sessions_timeout.is_running():
        check_sessions_timeout.start()


@bot.event
async def on_message(message: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.
    """
    # Don't delete this line! It's necessary for the bot to process commands.
    await bot.process_commands(message)

    # Ignore messages from self or other bots to prevent infinite loops.
    if message.author.bot or message.content.startswith("!"):
        return
    
    # Initialize user sessions dict if it doesn't exist
    if not hasattr(agent, 'user_sessions'):
        agent.user_sessions = {}
    
    user_id = str(message.author.id)
    
    # Check if this is a new conversation or continuing one
    flight_keywords = ["flight", "flights", "fly", "flying", "airline", "airport", "travel", "hotel", "booking"]
    is_travel_related = any(keyword in message.content.lower() for keyword in flight_keywords)
    
    # Start a new session only if user doesn't have one and message mentions travel
    if is_travel_related and user_id not in agent.user_sessions:
        agent.user_sessions[user_id] = {'active': True, 'last_interaction': message.created_at}
    
    # Process message if user has an active session OR message mentions travel
    if (user_id in agent.user_sessions and agent.user_sessions[user_id].get('active', False)) or is_travel_related:
        # If this is a travel message but user already has a session, just update the session
        if is_travel_related and user_id in agent.user_sessions:
            agent.user_sessions[user_id]['active'] = True
            agent.user_sessions[user_id]['last_interaction'] = message.created_at
        
        # Show typing indicator while processing
        async with message.channel.typing():
            # Process the message with the travel agent
            logger.info(f"Processing message from {message.author}: {message.content}")
            
            try:
                response = await agent.run(message)
                
                # Check if search parameters are available
                if os.path.exists('flight_search_params.json') and os.path.exists('hotel_search_params.json'):
                    # Load search parameters
                    with open('flight_search_params.json', 'r') as f:
                        flight_params = json.load(f)
                    with open('hotel_search_params.json', 'r') as f:
                        hotel_params = json.load(f)
                    
                    # Execute searches if parameters are complete
                    if all(value is not None for value in flight_params.values()):
                        from database import search_flights, search_hotels
                        await message.channel.send("🔍 Searching for the best travel options...")
                        
                        # Execute searches
                        search_flights(**flight_params)
                        search_hotels(**hotel_params)
                        
                        # Get the analysis from the agent
                        response = await agent.run(message)
                
                # Check if response is too long for Discord (2000 characters limit)
                if len(response) > 2000:
                    # Split into multiple messages
                    chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response)
                    
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await message.reply("I'm having trouble processing your request. Please try again later.")

# Commands

@bot.command(name="travel", help="Shows how to use the travel assistant")
async def travel(ctx):
    help_text = """
**Flight Assistant Help**

I can help you find the best flights based on your preferences. Here's how to use me:

1. Simply ask me to find flights in natural language, for example:
   - "Find me flights from NYC to LAX next week"
   - "What are the cheapest flights from Chicago to London in December?"

2. I'll ask follow-up questions if I need more details about:
   - Departure and return dates
   - Number of passengers
   - Class preference (economy, business, first)
   - Whether you want the cheapest or fastest options

3. Useful commands:
   - `!reset` - Start a new flight search
   - `!travel` - Show this help message

Just tell me where you want to go, and I'll do my best to find great flight options for you!
"""
    await ctx.send(help_text)


@bot.command(name="reset", help="Reset your flight search and start over")
async def reset(ctx):
    user_id = str(ctx.author.id)
    if hasattr(agent, 'user_sessions') and user_id in agent.user_sessions:
        agent.user_sessions[user_id]['active'] = False
    # Reset the conversation history
    agent.reset_conversation(user_id)
    await ctx.send("Your flight search has been reset. Ask me any flight-related questions to start a new search.")


# Start the bot, connecting it to the gateway
bot.run(token)