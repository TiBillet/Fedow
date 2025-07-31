import csv
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.validators import URLValidator
from django.db.transaction import atomic

from fedow_core.models import Place, Card, Origin


class Command(BaseCommand):
    # def add_arguments(self, parser):
        # Positional arguments
        # parser.add_argument('gen', action='store_true',
        #                     help='Generation')
        # parser.add_argument('place', action='store_true',
        #                     help='Generation')

    def is_string_an_url(self, url_string):
        validate_url = URLValidator()

        try:
            validate_url(url_string)
        except ValidationError as e:
            return False
        return True

    @atomic
    def handle(self, *args, **options):
        print(
            "CSV format: \n<url for qrcode: https://xxx.yyy.zzz/qr/uuid4>,<printed number : 8 char>,<RFID first_tag_id:8 char>\n")
        # file = open('data/retour_usine_raff_gen_2.csv')
        input_fichier_csv = input('path fichier csv ? \n')
        file = open(input_fichier_csv)

        # check doublon :
        tag_id_list = []
        url_qrcode_list = []
        number_list = []

        csv_parser = csv.reader(file)
        list_cards = []
        count = 1
        for line in csv_parser:
            url_qrcode = line[0]
            qr_code = UUID(url_qrcode.partition('/qr/')[2])
            tag_id = line[2].upper()
            number = line[1].upper()

            print(f"{count} url_qrcode: {url_qrcode}, number: {number}, tag_id: {tag_id}")

            if not self.is_string_an_url(url_qrcode):
                raise Exception('Url qrcode must be a valid url')

            if not type(number) == str or not len(number) == 8:
                raise Exception('Printed number must be 8 len string')
            if not type(tag_id) == str or not len(tag_id) == 8:
                raise Exception('Tag id must be 8 len string')

            if tag_id in tag_id_list :
                raise Exception('tag_id already exist in tag_id_list')
            if url_qrcode in url_qrcode_list :
                raise Exception('url_qrcode already exist in url_qrcode_list')
            if number in number_list :
                raise Exception('number already exist in number_list')

            if Card.objects.filter(first_tag_id=tag_id).exists():
                raise Exception('tag_id already exist in Card Database')
            if Card.objects.filter(number_printed=number).exists():
                raise Exception('number already exist in Card Database')
            if Card.objects.filter(qrcode_uuid=qr_code).exists():
                raise Exception('qr_code already exist in Card Database')

            tag_id_list.append(tag_id)
            url_qrcode_list.append(url_qrcode)
            number_list.append(number)

            list_cards.append((qr_code, number, tag_id))
            count += 1
        file.close()

        print(f'{len(list_cards)} card to import')
        print(f"Please select the origin place :")
        places = [place.name for place in Place.objects.all()]
        for index, place_name in enumerate(places):
            print(f"{index}, {place_name}")
        indexplace: str = input('\nnumber ? \n')
        choosen_place_name = places[int(indexplace)]
        place: Place = Place.objects.get(name=choosen_place_name)

        generation_nbr = input('\nEnter a generation number \n')
        generation_nbr = int(generation_nbr)

        origin, created = Origin.objects.get_or_create(
            place=place,
            generation=generation_nbr
        )

        for card in list_cards:
            qr_code = card[0]
            number = card[1]
            tag_id = card[2]
            print(f"Create : qr_code: {qr_code}, number: {number}, tag_id: {tag_id}")
            Card.objects.get_or_create(
                qrcode_uuid=qr_code,
                number_printed=number,
                first_tag_id=tag_id,
                origin=origin
            )
