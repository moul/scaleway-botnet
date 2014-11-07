NAME = ocs-botnet-worker
MASTER ?= 127.0.0.1
AMQP_USER ?= guest:guest

build:
	docker build -t $(NAME) .

run:
	docker run \
		-e AMQP_USER=$(AMQP_USER) \
		-e MASTER=$(MASTER) \
		-it --rm $(NAME)
