"""
Baseline for machine learning project on road segmentation.
This simple baseline consits of a CNN with two convolutional+pooling layers with a soft-max loss

Credits: Aurelien Lucchi, ETH Zürich

This was last tested with TensorFlow 1.13.2, which is not completely up to date.
To 'downgrade': pip install --upgrade tensorflow==1.13.2
"""

import gzip
import os
import sys
import urllib
from multiprocessing import pool
from utils.metrics import *
from utils.helpers import *

import matplotlib.image as mpimg
from PIL import Image

import numpy as np
import tensorflow as tf

# import tensorflow_addons as tfa

NUM_CHANNELS = 3  # RGB images
PIXEL_DEPTH = 255
NUM_LABELS = 2
TRAINING_SIZE = 20
VALIDATION_SIZE = 5  # Size of the validation set.
SEED = 66478  # Set to None for random seed.
BATCH_SIZE = 128  # 64
NUM_EPOCHS = 2
RESTORE_MODEL = False  # If True, restore existing model instead of training a new one
RECORDING_STEP = 0
REGULARIZATION_LAMBDA = 1e-6
LEAKY_RELU_ALPHA = 0.1

# Set image patch size in pixels
# IMG_PATCH_SIZE should be a multiple of 4
# image size should be an integer multiple of this number!
IMG_PATCH_SIZE = 16

tf.app.flags.DEFINE_string('train_dir', '../tmp/segment_aerial_images',
                           """Directory where to write event logs """
                           """and checkpoint.""")
FLAGS = tf.app.flags.FLAGS


def main(argv=None):  # pylint: disable=unused-argument

    data_dir = '../data/training/'
    train_data_filename = data_dir + 'images/'
    train_labels_filename = data_dir + 'groundtruth/'

    # Extract it into np arrays.
    train_data = extract_data(train_data_filename, TRAINING_SIZE, IMG_PATCH_SIZE)
    train_labels = extract_labels(train_labels_filename, TRAINING_SIZE, IMG_PATCH_SIZE)

    num_epochs = NUM_EPOCHS

    c0 = 0  # bgrd
    c1 = 0  # road
    for i in range(len(train_labels)):
        if train_labels[i][0] == 1:
            c0 = c0 + 1
        else:
            c1 = c1 + 1
    print('Number of data points per class: c0 = ' + str(c0) + ' c1 = ' + str(c1))

    print('Balancing training data...')
    min_c = min(c0, c1)
    idx0 = [i for i, j in enumerate(train_labels) if j[0] == 1]
    idx1 = [i for i, j in enumerate(train_labels) if j[1] == 1]
    new_indices = idx0[0:min_c] + idx1[0:min_c]
    print(len(new_indices))
    print(train_data.shape)
    train_data = train_data[new_indices, :, :, :]
    train_labels = train_labels[new_indices]

    train_size = train_labels.shape[0]

    print("train_size = " + str(train_size))

    c0 = 0
    c1 = 0
    for i in range(len(train_labels)):
        if train_labels[i][0] == 1:
            c0 = c0 + 1
        else:
            c1 = c1 + 1
    print('Number of data points per class: c0 = ' + str(c0) + ' c1 = ' + str(c1))

    # This is where training samples and labels are fed to the graph.
    # These placeholder nodes will be fed a batch of training data at each
    # training step using the {feed_dict} argument to the Run() call below.
    train_data_node = tf.placeholder(
        tf.float32,
        shape=(BATCH_SIZE, IMG_PATCH_SIZE, IMG_PATCH_SIZE, NUM_CHANNELS))
    train_labels_node = tf.placeholder(tf.float32,
                                       shape=(BATCH_SIZE, NUM_LABELS))
    train_all_data_node = tf.constant(train_data)

    # The variables below hold all the trainable weights. They are passed an
    # initial value which will be assigned when when we call:
    # {tf.initialize_all_variables().run()}
    conv1_weights = tf.Variable(
        tf.truncated_normal([5, 5, NUM_CHANNELS, 64],  # 5x5 filter, depth 64.
                            stddev=0.1,
                            seed=SEED))
    conv1_biases = tf.Variable(tf.zeros([64]))
    conv2_weights = tf.Variable(
        tf.truncated_normal([5, 5, 64, 128],
                            stddev=0.1,
                            seed=SEED))
    conv2_biases = tf.Variable(tf.constant(0.1, shape=[128]))
    fc1_weights = tf.Variable(  # fully connected, depth 512.
        tf.truncated_normal([int(IMG_PATCH_SIZE / 4 * IMG_PATCH_SIZE / 4 * 128), 512],
                            stddev=0.1,
                            seed=SEED))
    fc1_biases = tf.Variable(tf.constant(0.1, shape=[512]))
    fc2_weights = tf.Variable(
        tf.truncated_normal([512, NUM_LABELS],
                            stddev=0.1,
                            seed=SEED))
    fc2_biases = tf.Variable(tf.constant(0.1, shape=[NUM_LABELS]))

    # Get prediction for given input image

    def get_prediction(img):
        data = np.asarray(img_crop(img, IMG_PATCH_SIZE, IMG_PATCH_SIZE))
        data_node = tf.constant(data)
        output = tf.nn.softmax(model(data_node))
        output_prediction = s.run(output)
        img_prediction = label_to_img(img.shape[0], img.shape[1], IMG_PATCH_SIZE, IMG_PATCH_SIZE, output_prediction)

        return img_prediction

        # Get a concatenation of the prediction and groundtruth for given input file

    def get_prediction_with_groundtruth(filename, image_idx):
        imageid = "satImage_%.3d" % image_idx
        image_filename = filename + imageid + ".png"
        img = mpimg.imread(image_filename)

        img_prediction = get_prediction(img)
        cimg = concatenate_images(img, img_prediction, PIXEL_DEPTH)

        return cimg

    # Get prediction overlaid on the original image for given input file
    def get_prediction_with_overlay(filename, image_idx, pixel_depth):
        imageid = "satImage_%.3d" % image_idx
        image_filename = filename + imageid + ".png"
        img = mpimg.imread(image_filename)

        img_prediction = get_prediction(img)
        oimg = make_img_overlay(img, img_prediction, pixel_depth)

        return oimg

    # We will replicate the model structure for the training subgraph, as well
    # as the evaluation subgraphs, while sharing the trainable parameters.
    def model(data, train=False):
        """The Model definition."""
        # 2D convolution, with 'SAME' padding (i.e. the output feature map has
        # the same size as the input). Note that {strides} is a 4D array whose
        # shape matches the data layout: [image index, y, x, depth].
        conv = tf.nn.conv2d(data,
                            conv1_weights,
                            strides=[1, 1, 1, 1],
                            padding='SAME')
        # Bias and rectified linear non-linearity.
        relu = tf.nn.leaky_relu(tf.nn.bias_add(conv, conv1_biases), LEAKY_RELU_ALPHA)
        # Max pooling. The kernel size spec {ksize} also follows the layout of
        # the data. Here we have a pooling window of 2, and a stride of 2.
        pool = tf.nn.max_pool(relu,
                              ksize=[1, 2, 2, 1],
                              strides=[1, 2, 2, 1],
                              padding='SAME')

        conv2 = tf.nn.conv2d(pool,
                             conv2_weights,
                             strides=[1, 1, 1, 1],
                             padding='SAME')
        relu2 = tf.nn.leaky_relu(tf.nn.bias_add(conv2, conv2_biases), LEAKY_RELU_ALPHA)
        pool2 = tf.nn.max_pool(relu2,
                               ksize=[1, 2, 2, 1],
                               strides=[1, 2, 2, 1],
                               padding='SAME')

        # Uncomment these lines to check the size of each layer
        print('data ' + str(data.get_shape()))
        print('conv ' + str(conv.get_shape()))
        print('relu ' + str(relu.get_shape()))

        print('pool ' + str(pool.get_shape()))

        print('pool2 ' + str(pool2.get_shape()))

        # Reshape the feature map cuboid into a 2D matrix to feed it to the
        # fully connected layers.
        pool_shape = pool2.get_shape().as_list()
        reshape = tf.reshape(
            pool2,
            [pool_shape[0], pool_shape[1] * pool_shape[2] * pool_shape[3]])
        # Fully connected layer. Note that the '+' operation automatically
        # broadcasts the biases.
        hidden = tf.nn.leaky_relu(tf.matmul(reshape, fc1_weights) + fc1_biases, LEAKY_RELU_ALPHA)
        # Add a 50% dropout during training only. Dropout also scales
        # activations such that no rescaling is needed at evaluation time.
        if train:
            hidden = tf.nn.dropout(hidden, 0.5, seed=SEED)
        out = tf.matmul(hidden, fc2_weights) + fc2_biases

        if train:
            summary_id = '_0'
            s_data = get_image_summary(data, PIXEL_DEPTH)
            tf.summary.image('summary_data' + summary_id, s_data, max_outputs=3)
            s_conv = get_image_summary(conv, PIXEL_DEPTH)
            tf.summary.image('summary_conv' + summary_id, s_conv, max_outputs=3)
            s_pool = get_image_summary(pool, PIXEL_DEPTH)
            tf.summary.image('summary_pool' + summary_id, s_pool, max_outputs=3)
            s_conv2 = get_image_summary(conv2, PIXEL_DEPTH)
            tf.summary.image('summary_conv2' + summary_id, s_conv2, max_outputs=3)
            s_pool2 = get_image_summary(pool2, PIXEL_DEPTH)
            tf.summary.image('summary_pool2' + summary_id, s_pool2, max_outputs=3)
        return out

    # Training computation: logits + cross-entropy loss.
    logits = model(train_data_node, True)  # BATCH_SIZE*NUM_LABELS
    # print 'logits = ' + str(logits.get_shape()) + ' train_labels_node = ' + str(train_labels_node.get_shape())

    loss = tf.reduce_mean(
        tf.nn.softmax_cross_entropy_with_logits_v2(labels=train_labels_node,
                                                   logits=logits))

    tf.summary.scalar('loss', loss)

    all_params_node = [conv1_weights, conv1_biases, conv2_weights, conv2_biases, fc1_weights, fc1_biases, fc2_weights,
                       fc2_biases]
    all_params_names = ['conv1_weights', 'conv1_biases', 'conv2_weights', 'conv2_biases', 'fc1_weights', 'fc1_biases',
                        'fc2_weights', 'fc2_biases']
    all_grads_node = tf.gradients(loss, all_params_node)
    all_grad_norms_node = []
    for i in range(0, len(all_grads_node)):
        norm_grad_i = tf.global_norm([all_grads_node[i]])
        all_grad_norms_node.append(norm_grad_i)
        tf.summary.scalar(all_params_names[i], norm_grad_i)

    # L2 regularization for the fully connected parameters.
    regularizers = (tf.nn.l2_loss(fc1_weights) + tf.nn.l2_loss(fc1_biases) +
                    tf.nn.l2_loss(fc2_weights) + tf.nn.l2_loss(fc2_biases))
    # Add the regularization term to the loss.
    loss += REGULARIZATION_LAMBDA * regularizers

    # Optimizer: set up a variable that's incremented once per batch and
    # controls the learning rate decay.
    batch = tf.Variable(0)
    # Decay once per epoch, using an exponential schedule starting at 0.01.
    learning_rate = tf.train.exponential_decay(
        0.01,  # Base learning rate.
        batch * BATCH_SIZE,  # Current index into the dataset.
        train_size,  # Decay step.
        0.95,  # Decay rate.
        staircase=True)
    # tf.scalar_summary('learning_rate', learning_rate)
    tf.summary.scalar('learning_rate', learning_rate)

    # Use simple momentum for the optimization.
    optimizer = tf.train.MomentumOptimizer(learning_rate,
                                           0.0).minimize(loss,
                                                         global_step=batch)

    # Predictions for the minibatch, validation set and test set.
    train_prediction = tf.nn.softmax(logits)
    # We'll compute them only once in a while by calling their {eval()} method.
    train_all_prediction = tf.nn.softmax(model(train_all_data_node))

    # Add ops to save and restore all the variables.
    saver = tf.train.Saver()

    # Create a local session to run this computation.
    with tf.Session() as s:

        if RESTORE_MODEL:
            # Restore variables from disk.
            saver.restore(s, FLAGS.train_dir + "/model.ckpt")
            print("Model restored.")

        else:
            # Run all the initializers to prepare the trainable parameters.
            tf.global_variables_initializer().run()

            # Build the summary operation based on the TF collection of Summaries.
            summary_op = tf.summary.merge_all()
            summary_writer = tf.summary.FileWriter(FLAGS.train_dir,
                                                   graph=s.graph)

            print('Initialized!')
            # Loop through training steps.
            print('Total number of iterations = ' + str(int(num_epochs * train_size / BATCH_SIZE)))

            training_indices = range(train_size)

            preds = []
            labels = []

            for iepoch in range(num_epochs):

                # Permute training indices
                perm_indices = np.random.permutation(training_indices)

                steps_per_epoch = int(train_size / BATCH_SIZE)

                for step in range(steps_per_epoch):

                    offset = (step * BATCH_SIZE) % (train_size - BATCH_SIZE)
                    batch_indices = perm_indices[offset:(offset + BATCH_SIZE)]

                    # Compute the offset of the current minibatch in the data.
                    # Note that we could use better randomization across epochs.
                    batch_data = train_data[batch_indices, :, :, :]
                    batch_labels = train_labels[batch_indices]
                    # This dictionary maps the batch data (as a np array) to the
                    # node in the graph is should be fed to.
                    feed_dict = {train_data_node: batch_data,
                                 train_labels_node: batch_labels}

                    if step == 0:
                        summary_str, _, l, lr, predictions = s.run(
                            [summary_op, optimizer, loss, learning_rate, train_prediction],
                            feed_dict=feed_dict)
                        summary_writer.add_summary(summary_str, iepoch * steps_per_epoch)
                        summary_writer.flush()

                        print('Epoch %d' % iepoch)
                        print('Minibatch loss: %.3f, learning rate: %.6f' % (l, lr))
                        print('Minibatch error: %.1f%%' % error_rate(predictions,
                                                                     batch_labels))

                        sys.stdout.flush()
                    else:
                        # Run the graph and fetch some of the nodes.
                        _, l, lr, predictions = s.run(
                            [optimizer, loss, learning_rate, train_prediction],
                            feed_dict=feed_dict)

                    pred, batch_labels = one_hot_to_binary(predictions), one_hot_to_binary(batch_labels)
                    preds.append(pred)
                    labels.append(batch_labels)

                    # Save the variables to disk.
                save_path = saver.save(s, FLAGS.train_dir + "/model.ckpt")
                print("Model saved in file: %s" % save_path)

        f1_score = score(np.ndarray.flatten(np.asarray(preds)), np.ndarray.flatten(np.asarray(labels)))
        print("Running prediction on training set")
        prediction_training_dir = "predictions_training/"
        if not os.path.isdir(prediction_training_dir):
            os.mkdir(prediction_training_dir)
        for i in range(1, TRAINING_SIZE + 1):
            pimg = get_prediction_with_groundtruth(train_data_filename, i)
            Image.fromarray(pimg).save(prediction_training_dir + "prediction_" + str(i) + ".png")
            oimg = get_prediction_with_overlay(train_data_filename, i, PIXEL_DEPTH)
            oimg.save(prediction_training_dir + "overlay_" + str(i) + ".png")


if __name__ == '__main__':
    tf.app.run()
