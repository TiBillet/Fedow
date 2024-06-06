import csv
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.validators import URLValidator

from fedow_core.models import Place


class Command(BaseCommand):
    def is_string_an_url(self, url_string):
        validate_url = URLValidator()

        try:
            validate_url(url_string)
        except ValidationError as e:
            return False
        return True

    def handle(self, *args, **options):
        print(
            "CSV format: \n<url for qrcode: https://xxx.yyy.zzz/qr/uuid8>,<printed number : 8 char>,<RFID first_tag_id:8 char>\n")
        # file = open('data/retour_usine_raff_gen_2.csv')
        input_fichier_csv = input('path fichier csv ? \n')
        file = open(input_fichier_csv)

        csv_parser = csv.reader(file)
        list_card = []
        for line in csv_parser:
            url_qrcode = line[0]
            if not self.is_string_an_url(url_qrcode):
                raise Exception('Url qrcode must be a valid url')
            number = line[1].upper()
            if not type(number) == str or not len(number) == 8:
                raise Exception('Printed number must be 8 len string')
            tag_id = line[2].upper()
            if not type(tag_id) == str or not len(tag_id) == 8:
                raise Exception('Tag id must be 8 len string')

            print(f"url_qrcode: {url_qrcode}, number: {number}, tag_id: {tag_id}")
            list_card.append((tag_id, number, url_qrcode))
        file.close()

        print(f'{len(list_card)} card to import')
        print(f"Please select the origin place :")
        places = [place.name for place in Place.objects.all()]
        for index, place_name in enumerate(places):
            print(f"{index}, {place_name}")
        indexplace: str = input('\nnumber ? \n')
        choosen_place_name = places[int(indexplace)]
        place: Place = Place.objects.get(name=choosen_place_name)

        import ipdb; ipdb.set_trace()

