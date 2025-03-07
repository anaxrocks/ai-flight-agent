import os
import json
from mistralai import Mistral
import discord
from collections import defaultdict
from datetime import datetime, timedelta

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = """You are a helpful flight and hotel booking assistant. Follow these steps:
1. Gather all necessary information through conversation:
   - Origin and destination locations
   - Travel dates (departure and return)
   - Number of adults and children
   - Cabin class preference
   - Any specific preferences for hotels
2. Once you have all information, generate search parameters
3. After searches complete, analyze the results and present the best options

Always maintain context and ask for missing information politely."""

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
            'adults': None,
            'children': None,
            'cabin_class': None,
            'hotel_checkin': None,
            'hotel_checkout': None,
            'room_number': None
        }

    def parse_dates(self, date_str):
        """Convert various date formats to YYYY-MM-DD"""
        try:
            # Add more date formats as needed
            formats = [
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%m/%d/%Y",
                "%B %d, %Y",
                "%b %d, %Y"
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return None
        except:
            return None

    def generate_search_params(self, user_id):
        """Generate search parameters for both flights and hotels"""
        data = self.user_data[user_id]
        
        # Flight search parameters
        flight_params = {
            'from_id': data.get('origin'),
            'to_id': data.get('destination'),
            'depart_date': data.get('depart_date'),
            'return_date': data.get('return_date'),
            'page_no': '1',
            'adults': data.get('adults', 1),
            'children': data.get('children', 0),
            'sort': 'price_low_to_high',
            'cabin_class': data.get('cabin_class', 'ECONOMY'),
            'currency_code': 'USD'
        }

        # Hotel search parameters
        hotel_params = {
            'checkin_date': data.get('hotel_checkin'),
            'checkout_date': data.get('hotel_checkout'),
            'room_number': data.get('room_number', 1),
            'adults_number': data.get('adults', 1),
            'children_number': data.get('children', 0),
            'children_ages': [10] * int(data.get('children', 0)),  # Default age 10 for children
            'latitude': None,  # Will be filled after destination is confirmed
            'longitude': None  # Will be filled after destination is confirmed
        }

        # Save parameters to JSON files
        with open('flight_search_params.json', 'w') as f:
            json.dump(flight_params, f, indent=4)
        
        with open('hotel_search_params.json', 'w') as f:
            json.dump(hotel_params, f, indent=4)

        return flight_params, hotel_params

    def analyze_results(self):
        """Analyze the results from both flight and hotel searches"""
        try:
            with open('flight_options.json', 'r') as f:
                flight_results = json.load(f)
            with open('hotel_options.json', 'r') as f:
                hotel_results = json.load(f)

            # Format the results into a user-friendly message
            response = "Here are the best travel options I found:\n\n"
            
            # Add flight information
            response += "🛫 **Best Flight Options:**\n"
            for i, flight in enumerate(flight_results[:3], 1):
                response += f"{i}. {flight.get('airline_name', 'Airline')} Flight {flight.get('flight_number', '')}\n"
                response += f"   • {flight.get('departure_airport')} → {flight.get('arrival_airport')}\n"
                response += f"   • Departure: {flight.get('departure_time')}\n"
                response += f"   • Duration: {flight.get('duration')}\n"
                if flight.get('price'):
                    response += f"   • Price: ${flight['price'].get('amount', 'N/A')} {flight['price'].get('currency', 'USD')}\n"
                response += "\n"

            # Add hotel information
            response += "\n🏨 **Best Hotel Options:**\n"
            for i, hotel in enumerate(hotel_results[:3], 1):
                response += f"{i}. {hotel.get('name', 'Hotel Name')}\n"
                response += f"   • Price: ${hotel.get('price', 'N/A')} per night\n"
                if hotel.get('review_score'):
                    response += f"   • Rating: {hotel.get('review_score')}/10\n"
                response += "\n"

            return response
        except Exception as e:
            return f"I apologize, but I encountered an error analyzing the results: {str(e)}"

    async def run(self, message: discord.Message):
        user_id = str(message.author.id)
        
        # Initialize user data if not exists
        if user_id not in self.user_data:
            self.user_data[user_id] = self.get_required_fields()

        # Build the messages list starting with system prompt
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.conversation_history[user_id])
        messages.append({"role": "user", "content": message.content})

        # Get response from Mistral
        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        assistant_response = response.choices[0].message.content

        # Update conversation history
        self.conversation_history[user_id].append({"role": "user", "content": message.content})
        self.conversation_history[user_id].append({"role": "assistant", "content": assistant_response})

        # Maintain history size limit
        if len(self.conversation_history[user_id]) > self.max_history * 2:
            self.conversation_history[user_id] = self.conversation_history[user_id][-self.max_history * 2:]

        # Check if we have all required information
        all_fields_filled = all(value is not None for value in self.user_data[user_id].values())
        
        if all_fields_filled:
            # Generate search parameters
            self.generate_search_params(user_id)
            # Return analysis of results if available
            try:
                if os.path.exists('flight_options.json') and os.path.exists('hotel_options.json'):
                    return self.analyze_results()
            except Exception as e:
                pass

        return assistant_response

    def reset_conversation(self, user_id: str):
        """Reset the conversation history and user data for a specific user"""
        self.conversation_history[user_id] = []
        self.user_data[user_id] = self.get_required_fields()
