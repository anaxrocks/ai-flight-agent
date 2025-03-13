import os
import json
from mistralai import Mistral
import discord
import requests
import json
from datetime import datetime
from collections import defaultdict
from datetime import datetime, timedelta
from database import search_flights, search_hotels

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = """You are a helpful flight and hotel booking assistant. Your task is to:
1. Extract travel information from user messages and store it in the correct format:
   - Origin airport (must end in .AIRPORT, e.g., 'JFK.AIRPORT')
   - Destination airport (must end in .AIRPORT, e.g., 'LAX.AIRPORT')
   - Departure date (YYYY-MM-DD format, assume year 2025 if not specified)
   - Return date (YYYY-MM-DD format, assume year 2025 if not specified)
   - Number of adults (integer)
   - Number of children (integer)
   - Children's ages (comma-separated string, e.g., "5,0")
   - Cabin class (must be: ECONOMY, BUSINESS, or FIRST)
   - Sort preference (must be: BEST, PRICE, DURATION)
   - Hotel search parameters:
     * Destination coordinates (estimate based on city, e.g., New York would be around latitude: 40.776676, longitude: -73.971321)
     * Room number (integer)
     * Hotel category (must be: "class::2,class::4,free_cancellation::1")

When you identify these details in the user's message, include them in your response using this format:
<travel_data>
{
    "origin": "XXX.AIRPORT",
    "destination": "XXX.AIRPORT",
    "depart_date": "YYYY-MM-DD",
    "return_date": "YYYY-MM-DD",
    "adults": 2,
    "children": 2,
    "children_ages": "5,0",
    "cabin_class": "ECONOMY",
    "sort": "BEST",
    "destination_latitude": 40.776676,  # Example for New York
    "destination_longitude": -73.971321,  # Example for New York
    "room_number": 1,
    "hotel_category": "class::2,class::4,free_cancellation::1"
}
</travel_data>

Always format airport codes with .AIRPORT suffix.
Maintain a natural conversation while gathering missing information.
If a user mentions a city without an airport code, ask for clarification about which airport they prefer.

For hotel searches, ensure these exact parameters:
- Estimate destination coordinates based on the destination city (e.g., New York ≈ 40.776676, -73.971321)
- categories_filter_ids must be "class::2,class::4,free_cancellation::1"
- page_number must be 0
- units must be "metric"
- locale must be "en-gb"
- include_adjacency must be "true"
- order_by must be "popularity"
- filter_by_currency must be "USD"
- Format children_ages as a comma-separated string (e.g., "5,0")"""

class MistralAgent:
    def __init__(self):
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)
        self.conversation_history = defaultdict(list)
        self.user_data = defaultdict(dict)
        self.max_history = 10

    def get_required_fields(self):
        return {
            'origin': None,
            'destination': None,
            'depart_date': None,
            'return_date': None,
            'adults': 1,
            'children': 1,
            'children_ages': '0',
            'cabin_class': 'ECONOMY',
            'sort': 'BEST',
            'currency_code': 'USD',
            'room_number': 1,
            'destination_latitude': None,
            'destination_longitude': None,
            'hotel_category': "class::2,class::4,free_cancellation::1"
        }

    def format_airport_code(self, code):
        """Ensure airport code is properly formatted"""
        if not code:
            return None
        code = code.upper().strip()
        if not code.endswith('.AIRPORT'):
            code = f"{code}.AIRPORT"
        return code

    def generate_search_params(self, user_id):
        """Generate search parameters for both flight and hotel searches"""
        data = self.user_data[user_id]
        
        # Flight search parameters with proper formatting
        flight_params = {
            'from_id': self.format_airport_code(data.get('origin')),
            'to_id': self.format_airport_code(data.get('destination')),
            'depart_date': data.get('depart_date'),
            'return_date': data.get('return_date'),
            'page_no': 1,
            'adults': int(data.get('adults', 1)),
            'children': str(data.get('children', '0')),  # Keep original value for flights
            'sort': data.get('sort', 'BEST'),
            'cabin_class': data.get('cabin_class', 'ECONOMY'),
            'currency_code': data.get('currency_code', 'USD')
        }

        # Hotel search parameters matching exactly what search_hotels expects
        hotel_params = {
            'latitude': data.get('destination_latitude'),
            'longitude': data.get('destination_longitude'),
            'checkin_date': data.get('depart_date'),
            'checkout_date': data.get('return_date'),
            'room_number': int(data.get('room_number', 1)),
            'adults_number': int(data.get('adults', 1)),
            'children_number': max(1, int(data.get('children', 0))),  # Ensure minimum of 1 child for hotels only
            'children_ages': '0'  # Always set to '0' since we always have at least 1 child for hotels
        }

        return flight_params, hotel_params

    async def run(self, message: discord.Message):
        user_id = str(message.author.id)
        
        # Initialize user data if not exists
        if user_id not in self.user_data:
            self.user_data[user_id] = self.get_required_fields()

        # Build the messages list starting with system prompt
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add context about what information we already have
        context = "Current travel information:\n"
        for field, value in self.user_data[user_id].items():
            if value is not None:
                context += f"- {field}: {value}\n"
        messages.append({"role": "system", "content": context})
        
        # Add conversation history
        messages.extend(self.conversation_history[user_id])
        messages.append({"role": "user", "content": message.content})

        # Get response from Mistral
        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        assistant_response = response.choices[0].message.content

        # Extract travel data if present in the response
        if "<travel_data>" in assistant_response and "</travel_data>" in assistant_response:
            try:
                data_start = assistant_response.index("<travel_data>") + len("<travel_data>")
                data_end = assistant_response.index("</travel_data>")
                data_str = assistant_response[data_start:data_end].strip()
                travel_data = json.loads(data_str)
                
                # Update user data with new information
                self.user_data[user_id].update(travel_data)
                
                # Remove the travel data section from the response
                assistant_response = assistant_response[:data_start-len("<travel_data>")] + assistant_response[data_end+len("</travel_data>"):]
            except json.JSONDecodeError:
                pass

        # Update conversation history
        self.conversation_history[user_id].append({"role": "user", "content": message.content})
        self.conversation_history[user_id].append({"role": "assistant", "content": assistant_response})

        # Maintain history size limit
        if len(self.conversation_history[user_id]) > self.max_history * 2:
            self.conversation_history[user_id] = self.conversation_history[user_id][-self.max_history * 2:]

        # Check if we have all required information
        required_fields = ['origin', 'destination', 'depart_date', 'return_date']
        all_fields_filled = all(self.user_data[user_id].get(field) is not None for field in required_fields)
        
        if all_fields_filled:
            try:
                # Generate search parameters
                flight_params, hotel_params = self.generate_search_params(user_id)
                
                # Execute the searches
                await message.channel.send("🔍 Searching for flights and hotels with your criteria...")
                
                # Execute flight search
                search_flights(**flight_params)
                
                # Execute hotel search if we have coordinates
                if hotel_params['latitude'] and hotel_params['longitude']:
                    try:
                        print(f"Attempting hotel search with params: {hotel_params}")  # Debug print
                        search_hotels(**hotel_params)
                        if not os.path.exists('hotel_options.json'):
                            print("Hotel search completed but no JSON file was created")
                    except Exception as hotel_error:
                        print(f"Hotel search error: {str(hotel_error)}")
                        await message.channel.send(f"⚠️ Note: Could not complete hotel search: {str(hotel_error)}")
                else:
                    print(f"Missing coordinates. Latitude: {hotel_params['latitude']}, Longitude: {hotel_params['longitude']}")
                    await message.channel.send("⚠️ Note: Could not search for hotels - missing location coordinates")
                
                # Analyze and combine results
                response = "Here are the travel options I found:\n\n"
                
                # Add flight results
                if os.path.exists('flight_options.json'):
                    with open('flight_options.json', 'r') as f:
                        flight_results = json.load(f)
                        
                    if flight_results:
                        response += "🛫 **Flight Options:**\n"
                        for i, flight in enumerate(flight_results[:3], 1):
                            response += f"{i}. {flight.get('airline_name', 'Airline')} Flight {flight.get('flight_number', '')}\n"
                            response += f"   • Route: {flight.get('departure_airport')} ({flight.get('departure_terminal', '')}) → {flight.get('arrival_airport')} ({flight.get('arrival_terminal', '')})\n"
                            response += f"   • Departure: {flight.get('departure_time')}\n"
                            response += f"   • Arrival: {flight.get('arrival_time')}\n"
                            response += f"   • Duration: {flight.get('duration')}\n"
                            response += f"   • Stops: {flight.get('stops', 0)}\n"
                            if flight.get('price'):
                                response += f"   • Price: ${flight['price'].get('amount', 'N/A')} {flight['price'].get('currency', 'USD')}\n"
                            response += "\n"
                
                # Add hotel results
                if os.path.exists('hotel_options.json'):
                    with open('hotel_options.json', 'r') as f:
                        hotel_results = json.load(f)
                        
                    if hotel_results:
                        response += "\n🏨 **Hotel Options:**\n"
                        for i, hotel in enumerate(hotel_results[:3], 1):
                            response += f"{i}. {hotel.get('name', 'Hotel Name')}\n"
                            response += f"   • Total price: ${hotel.get('price', 'N/A')}\n"
                            if hotel.get('review_score'):
                                response += f"   • Rating: {hotel.get('review_score')}/10\n"
                            response += f"   • Check-in: {hotel_params['checkin_date']}\n"
                            response += f"   • Check-out: {hotel_params['checkout_date']}\n"
                            response += "\n"
                
                if response == "Here are the travel options I found:\n\n":
                    return "I searched but couldn't find any matches. Would you like to try different dates or locations?"
                
                return response
                
            except Exception as e:
                return f"I encountered an error while searching: {str(e)}"

        return assistant_response

    def reset_conversation(self, user_id: str):
        """Reset the conversation history and user data for a specific user"""
        self.conversation_history[user_id] = []
        self.user_data[user_id] = self.get_required_fields()
        
        # Delete JSON files if they exist
        if os.path.exists('flight_options.json'):
            os.remove('flight_options.json')
        if os.path.exists('hotel_options.json'):
            os.remove('hotel_options.json')
