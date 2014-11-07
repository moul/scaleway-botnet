FROM armbuild/dockerfile-celery
RUN pip install redis
ENV C_FORCE_ROOT 1
ADD ./ocs.py /data/ocs.py
CMD celery worker -B -A ocs -l INFO
