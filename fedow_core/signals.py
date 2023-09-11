"""
from django.db.models.signals import pre_save
from django.dispatch import receiver

from fedow_core.models import CheckoutStripe, Transaction
import logging
logger = logging.getLogger(__name__)


def error_regression(old_instance, new_instance):
    logger.error(f"models_signal erreur_regression {old_instance.status} to {new_instance.status}")
    pass




PRE_SAVE_TRANSITIONS = {
    'PAIEMENT_STRIPE': {
        CheckoutStripe.OPEN: {
            CheckoutStripe.PAID: create_transaction,
            '_else_': error_regression,
        },
        CheckoutStripe.PAID: {
            '_all_': error_regression,
        }
    },
}


# Pour tout les modèls qui possèdent un système de status choice
@receiver(pre_save, sender=CheckoutStripe)
def pre_save_signal_status(sender, instance, **kwargs):
    # if not create
    if not instance._state.adding:
        sender_str = sender.__name__.upper()
        dict_transition = PRE_SAVE_TRANSITIONS.get(sender_str)

        if dict_transition:
            old_instance = sender.objects.get(pk=instance.pk)
            new_instance = instance
            transitions = dict_transition.get(old_instance.status, None)
            if transitions:
                # Par ordre de préférence :
                trigger_function = transitions.get('_all_', (
                    transitions.get(new_instance.status, (
                        transitions.get('_else_', None)
                    ))))

                if trigger_function:
                    if not callable(trigger_function):
                        raise Exception(f'Fonction {trigger_function} is not callable. Disdonc !?')
                    trigger_function(old_instance, new_instance)

"""
