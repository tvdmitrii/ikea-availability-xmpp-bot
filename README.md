# IKEA Availability XMPP Bot
Back around August of 2021, I was trying to buy a Friheten couch from IKEA. Unfortunately, non were available, and the "Notify Me" emails would never come through even though we were assured that a couple of couches did arrive and were sold. Digging through the IKEA website with developer tools, I found that they expose their API which provides more detailed information than simple "In Stock", "Low", and "Out of Stock". It not only has information about the exact number available but also has information about future shipments with a date, quantity, and even probability. Luckily for me, people already knew about it and created [ikea-availability-checker](https://github.com/Ephigenia/ikea-availability-checker) project and put it on GitHub. It decided to combine this project with [Slixmpp](https://pypi.org/project/slixmpp/) a Python library for XMPP.

It did secure a couch for me a few months later!

# Description
For the bot to work, you need to:
- Install Slixmpp
- Install ikea-availability-checker
- Have a running XMPP server
- Figure out the store ID and IDs of items you are interested in. Include these in the IkeaBot constructor. (This is messy, but oh well. Should have made a config file for these things.)
- Provide JIDs of people to receive notifications (also in the IkeaBot constructor)
- Provide JID and password for the bot, as well as delay in seconds which defines how often to check for availability (provided in main).
- The bot responds to "status" message on demand, providing current availability and information about future shipments
- The bot pulls the API every X amount of time to check whether availability is >0 at which point it will begin sending you messages

# Learning Outcomes
This has been a fun project and a great opportunity to learn about XMPP, and OMEMO end-to-end encryption. Getting OMEMO working was not easy!

# Possible Development
This could be the first building block for a cool, secure, and self-hosted home automation/information system. You could ask your home server for status, your router for connected clients, and maybe even your fridge for available food. You could also send commands to restart machines, adjust heating/cooling, or do anything else you wish. This is why the class is called "Coordinator". It was supposed to handle multiple bots.

# Disclaimer
† This website is not run by or affiliated with Inter-IKEA Systems B.V. or its related business entities.
IKEA® is a registered trademark of Inter-IKEA Systems B.V. in the U.S. and other countries. 
