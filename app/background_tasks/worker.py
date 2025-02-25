from app.background_tasks.workflows import (
    send_mail_workflow,
    skb_order_workflow,
)


if __name__ == "__main__":
    send_mail_workflow.serve(name="send-mail-workflow")
    skb_order_workflow.serve(name="skb-order-workflow")
