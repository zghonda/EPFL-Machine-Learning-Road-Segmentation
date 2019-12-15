
import os

from src.unet_keras import *
from utils.helpers import *

# Loaded a set of images
ROOT_DIR = "/content/drive/My Drive/Road_Segmentation/data/training/"

IMG_SIZE = 400
NUM_CHANNELS = 3
NUM_FILTER = 32
FILTER_SIZE = 3

BATCH_SIZE = 16
NUM_EPOCHS = 200


def main(argv=None):

    image_dir = ROOT_DIR + "images/"
    gt_dir = ROOT_DIR + "groundtruth/"

    files = os.listdir(image_dir)
    n = len(files)

    print("Loading " + str(n) + " images")
    imgs = [load_image(image_dir + files[i]) for i in range(n)]

    print("Loading " + str(n) + " groundtruth images")
    gt_imgs = [load_image(gt_dir + files[i]) for i in range(n)]

    x_train = np.asarray(imgs)
    y_train = np.expand_dims(np.asarray(gt_imgs), axis=3)

    # Create Model
    model = unet_model(IMG_SIZE, NUM_CHANNELS, NUM_FILTER, FILTER_SIZE, leaky=True, dropout=0.5)

    # Run Model
    model = train_model(model, x_train, y_train, BATCH_SIZE, NUM_EPOCHS)

    # Save the trained model
    print('Saving trained model')
    new_model_filename = 'unet_leaky_0val_50drop_200epo.h5'
    model.save(new_model_filename)


if __name__ == '__main__':
    tf.app.run()
