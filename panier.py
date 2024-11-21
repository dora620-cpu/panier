
import cv2
import roboflow
import numpy as np
import subprocess
import RPi.GPIO as GPIO
from time import sleep, time
import requests
from RPLCD.gpio import CharLCD
from hx711 import HX711

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Initialisation du LCD avec les broches connectées à votre Raspberry Pi
lcd = CharLCD(numbering_mode=GPIO.BCM, cols=16, rows=2, pin_rs=26, pin_e=19, pins_data=[11, 16, 20, 21])
lcd.clear()

BUZZER_PIN = 12
BUTTON_PIN = 17  # Broche GPIO pour le bouton poussoir

GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Bouton poussoir avec résistance de pull-up interne

# Initialiser la connexion avec Roboflow
rf = roboflow.Roboflow(api_key="VNKiFa7COKW3eT6pkOhJ")
project = rf.workspace().project("shopp-cart")
model = project.version("1").model

# Récupération des produits depuis l'endpoint
def get_products():
    response = requests.get("https://computer-vision-caddie-ai.onrender.com/products/products")
    if response.status_code == 200:
        print(response.json())
        return response.json()
    return []

# Capture d'image
def capture_image():
    subprocess.run(["libcamera-still", "-o", "temp_image.jpg"])

# Traitement d'image et détection d'objets
def process_image():
    capture_image()
    frame = cv2.imread("temp_image.jpg")
    if frame is None:
        print("Erreur lors du chargement de l'image.")
        return {}

    predictions = model.predict("temp_image.jpg", confidence=40, overlap=30).json()
    detected_objects = {}
    for obj in predictions['predictions']:
        class_name = obj['class']
        if class_name in detected_objects:
            detected_objects[class_name] += 1
        else:
            detected_objects[class_name] = 1
    
    return detected_objects

# Affichage sur le LCD
def update_lcd(product_name, product_price, quantity):
    lcd.clear()
    lcd.write_string(f"{quantity} x {product_name}")
    lcd.cursor_pos = (1, 0)
    lcd.write_string(f"Prix: {product_price * quantity:.2f} EUR")

# Affichage du total sur le LCD
def display_total(total_price):
    lcd.clear()
    lcd.write_string("Total a payer:")
    lcd.cursor_pos = (1, 0)
    lcd.write_string(f"{total_price:.2f} EUR")

# Émission du signal sonore via le buzzer
def beep_buzzer():
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    sleep(0.2)
    GPIO.output(BUZZER_PIN, GPIO.LOW)

# Validation du panier
def validate_cart(cart, cart_number):
    # Préparer les données pour l'envoi
    cart_data = {
        "cartNumber": cart_number,
        "products": [{"productId": item["productId"], "quantity": item["quantity"]} for item in cart.values()]
    }
    
    # Envoyer les données au serveur
    endpoint = "https://computer-vision-caddie-ai.onrender.com/purchases/adds"
    response = requests.post(endpoint, json=cart_data)
    
    if response.status_code == 200:
        print("Panier validé avec succès.")
    else:
        print("Erreur lors de la validation du panier.")

# Fonction d'interruption pour le bouton poussoir
def button_pressed(channel):
    global cart, total_price
    if len(cart) > 0:
        sleep(2)  # Pause pour laisser l'utilisateur voir l'ajout
        display_total(total_price)
        sleep(5)  # Afficher le total pendant 5 secondes
        cart_number = 2  # Vous pouvez définir une logique pour le numéro de panier, par exemple un compteur ou un ID unique
        validate_cart(cart, cart_number)

        # Réinitialiser le panier et le total pour la prochaine personne
        cart.clear()
        total_price = 0
        lcd.clear()
        lcd.write_string("Nouveau client...")
        sleep(2)  # Pause pour indiquer la réinitialisation avant de recommencer

# Configurer l'interruption pour le bouton poussoir
GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, callback=button_pressed, bouncetime=300)

# Comparer et mettre à jour le panier en fonction des objets détectés
def update_cart_with_detected_objects(detected_objects):
    global cart, total_price
    # Créer une copie des produits actuels dans le panier pour les comparer
    current_cart = cart.copy()

    # Mise à jour des produits dans le panier
    for class_name, quantity in detected_objects.items():
        for product in products:
            if product['name'].lower() == class_name.lower():
                product_id = product['_id']
                
                # Si le produit est déjà dans le panier, on met à jour la quantité
                if product_id in cart:
                    previous_quantity = cart[product_id]["quantity"]
                    cart[product_id]["quantity"] = quantity
                    
                    # Calculer la différence de quantité pour ajuster le prix total
                    quantity_diff = quantity - previous_quantity
                    total_price += product['price'] * quantity_diff
                else:
                    # Si le produit n'est pas dans le panier, on l'ajoute
                    cart[product_id] = {
                        "productId": product_id,
                        "quantity": quantity,
                        "price": product['price'],
                        "name": product['name']
                    }
                    total_price += product['price'] * quantity
                
                # Mettre à jour l'affichage sur le LCD pour ce produit
                update_lcd(product['name'], product['price'], quantity)
                break

    # Parcourir les produits du panier actuel et détecter les produits retirés
    for product_id in current_cart:
        if current_cart[product_id]["name"].lower() not in detected_objects:
            # Si le produit n'est plus détecté, il a été retiré
            removed_quantity = cart[product_id]["quantity"]
            total_price -= cart[product_id]["price"] * removed_quantity
            del cart[product_id]  # Retirer le produit du panier
            print(f"{current_cart[product_id]['name']} retiré du panier.")

# Programme principal avec gestion des ajouts et retraits toutes les 30 secondes
if __name__ == "__main__":
    try:
        products = get_products()
        cart = {}
        total_price = 0

        last_detection_time = time()

        while True:
            # Vérifier si 30 secondes se sont écoulées depuis la dernière détection
            if time() - last_detection_time >= 30:
                beep_buzzer()

                # Détection des objets après délai
                detected_objects = process_image()

                # Mise à jour du panier en fonction des objets détectés
                update_cart_with_detected_objects(detected_objects)

                print("Objets détectés:", detected_objects)
                print("Panier actuel:", cart)

                last_detection_time = time()  # Réinitialiser le temps

            sleep(1)

    except KeyboardInterrupt:
        print("Arrêt du programme.")
    finally:
        GPIO.cleanup()
        lcd.clear()